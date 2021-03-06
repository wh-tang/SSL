# This code is modified from: https://github.com/linusericsson/ssl-invariances/blob/main/eval_synthetic_invariance.py

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, ConcatDataset
from torch.utils.data.sampler import SubsetRandomSampler
from torchvision import datasets, models, transforms

import os
import PIL
from PIL import Image
import pickle
import argparse
import logging
from pprint import pprint
from tqdm import tqdm
from pathlib import Path
from itertools import product

import numpy as np
from scipy.spatial.distance import mahalanobis

from datasets.transforms import HistogramNormalize
from datasets.custom_chexpert_dataset import CustomChexpertDataset
from datasets.custom_diabetic_retinopathy_dataset import CustomDiabeticRetinopathyDataset 

from models.backbones import ResNetBackbone, ResNet18Backbone, DenseNetBackbone


def D(a, b): # cosine similarity
    return F.cosine_similarity(a, b, dim=-1).mean()

# Data classes and functions


def get_dataset(dset, root, split, transform, group_front_lateral=False):
    if group_front_lateral:
        return dset(root, train=(split == 'train'), transform=transform, download=True,
                group_front_lateral=group_front_lateral)
    else:
        return dset(root, train=(split == 'train'), transform=transform, download=True)


def get_train_valid_test_dset(dset,
                              data_dir,
                              normalise_dict,
                              hist_norm,
                              image_size,
                              group_front_lateral=False):

    
    normalize = transforms.Normalize(**normalise_dict)

    # define transforms
    if hist_norm:
        transform = transforms.Compose([
            transforms.Resize(image_size, interpolation=PIL.Image.BICUBIC),
            transforms.CenterCrop(image_size),
            transforms.ToTensor(),
            HistogramNormalize(),
        ])
    else:
        transform = transforms.Compose([
            transforms.Resize(image_size, interpolation=PIL.Image.BICUBIC),
            transforms.CenterCrop(image_size),
            transforms.ToTensor(),
            normalize,
        ])
    
    train_valid_dataset = get_dataset(dset, data_dir, 'train', transform, group_front_lateral=group_front_lateral)
    test_dataset = get_dataset(dset, data_dir, 'test', transform, group_front_lateral=group_front_lateral)
    dataset = ConcatDataset([train_valid_dataset, test_dataset])

    return dataset









# name: {class, root}
DATASETS = {
    'chexpert' : [CustomChexpertDataset, './data/chexpert'],
    'diabetic_retinopathy' : [CustomDiabeticRetinopathyDataset, './data/diabetic_retinopathy'],
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', default='chexpert', type=str,
                        help='name of the dataset to evaluate on')
    parser.add_argument('--model', default='moco-v2', type=str,
                        help='model to evaluate invariance of')
    parser.add_argument('--transform', default='multi_view', type=str,
                        help='transform to evaluate invariance of')
    parser.add_argument('--device', default='cuda', type=str, help='GPU device')
    parser.add_argument('--num-images', default=100, type=int, help='number of images to evaluate invariance on')
    parser.add_argument('--batch-size', default=256, type=int, help='mini-batch size')
    parser.add_argument('--image-size', default=224, type=int, help='image size')
    parser.add_argument('-n', '--no-norm', action='store_true', default=False,
                        help='whether to turn off data normalisation (based on ImageNet values)')
    args = parser.parse_args()
    args.norm = not args.no_norm
    del args.no_norm
    pprint(args)

    # histogram normalization
    hist_norm = False
    if 'mimic-chexpert' in args.model:
        hist_norm = True


    # set-up logging
    log_fname = f'{args.dataset}.log'
    if not os.path.isdir(f'./logs/invariances/{args.model}/{args.transform}'):
        os.makedirs(f'./logs/invariances/{args.model}/{args.transform}')
    log_path = os.path.join(f'./logs/invariances/{args.model}/{args.transform}', log_fname)
    logging.basicConfig(filename=log_path, filemode='w', level=logging.INFO)
    logging.info(args)


    # load pretrained model
    if args.model in ['mimic-chexpert_lr_0.1', 'mimic-chexpert_lr_0.01', 'mimic-chexpert_lr_1.0', 'supervised_d121']:
        model = DenseNetBackbone(args.model)
        feature_dim = 1024
    elif 'mimic-cxr' in args.model:
        if 'r18' in args.model:
            model = ResNet18Backbone(args.model)
            feature_dim = 512
        else:
            model = DenseNetBackbone(args.model)
            feature_dim = 1024
    elif args.model == 'supervised_r18':
        model = ResNet18Backbone(args.model)
        feature_dim = 512
    else:
        model = ResNetBackbone(args.model)
        feature_dim = 2048
    
    model = model.to(args.device)


    if args.norm:
        mean_std = [[0.485, 0.456, 0.406], [0.229, 0.224, 0.225]]
        normalise_dict = {'mean': [0.485, 0.456, 0.406], 'std': [0.229, 0.224, 0.225]}
    else:
        mean_std = [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]
        normalise_dict = {'mean': [0.0, 0.0, 0.0], 'std': [1.0, 1.0, 1.0]}

    # load datasets
    dset, data_dir = DATASETS[args.dataset]
    clean_dataset = dataset = get_train_valid_test_dset(dset, data_dir, normalise_dict, hist_norm, args.image_size, group_front_lateral=False)
    multi_views_dataset = get_train_valid_test_dset(dset, data_dir, normalise_dict, hist_norm, args.image_size, group_front_lateral=True)

    # set random seeds
    np.random.seed(0)
    torch.manual_seed(0)


    if os.path.exists(f'./misc/invariances/{args.model}_{args.dataset}_feature_cov_matrix.pth'):
        print(f'Found precomputed covariance matrix for {args.model} on {args.dataset}, skipping it')
        logging.info(f'Found precomputed covariance matrix for {args.model} on {args.dataset}, skipping it')
    else:
        print(f'Computing covariance matrix for {args.model} on dataset {args.dataset}')
        logging.info(f'Computing covariance matrix for {args.model} on dataset {args.dataset}')

        # Calculate (approx.) mean and covariance matrix, 
        # from > 1000 sampled images (10% of full dataset, or full dataset if contains < 1000 images)
        if len(clean_dataset) < 1000:
            clean_dataloader = DataLoader(clean_dataset, batch_size=args.batch_size)
        else:
            random_idx = np.random.choice(np.arange(len(clean_dataset)), max(1000, int(0.1*len(clean_dataset))))
            sub_sampler = SubsetRandomSampler(random_idx)
            clean_dataloader = DataLoader(clean_dataset, batch_size=args.batch_size, sampler=sub_sampler)


        all_features = []
        with torch.no_grad():
            progress = tqdm(clean_dataloader)
            for data, _ in progress:
                data = data.to(args.device)
                features = model(data).detach().cpu()
                all_features.append(features)
        all_features = torch.cat(all_features)

        mean_feature = all_features.mean(dim=0)
        cov_matrix = np.cov(all_features, rowvar=False)

        torch.save(mean_feature, f'./misc/invariances/{args.model}_{args.dataset}_mean_feature.pth')
        torch.save(cov_matrix, f'./misc/invariances/{args.model}_{args.dataset}_feature_cov_matrix.pth')


    # Calculate invariances
    L = torch.zeros((args.num_images,))
    S = torch.zeros((args.num_images,))

    mean_feature = torch.load(f'./misc/invariances/{args.model}_{args.dataset}_mean_feature.pth')
    cov_matrix = torch.load(f'./misc/invariances/{args.model}_{args.dataset}_feature_cov_matrix.pth')
    
    epsilon = 1e-6
    cov_matrix = cov_matrix + epsilon * np.eye(cov_matrix.shape[0])
    inv_cov_matrix = np.linalg.inv(cov_matrix)
    cholesky_matrix = torch.linalg.cholesky(torch.from_numpy(inv_cov_matrix).to(torch.float32))


    dataloader = DataLoader(multi_views_dataset, batch_size=1, shuffle=True) 
    with torch.no_grad():
        for i in tqdm(range(args.num_images)):
            (view_1, view_2), _ = next(iter(dataloader))
            feature_1 = model(view_1.to(args.device)).detach().cpu()
            feature_2 = model(view_2.to(args.device)).detach().cpu()

            a = (mean_feature - feature_1) @ cholesky_matrix
            b = (mean_feature - feature_2) @ cholesky_matrix
            S[i] = D(a, b) # cosine similarity
            L[i] = mahalanobis(feature_1, feature_2, inv_cov_matrix) # mahalanobis distance

    L = np.nanmean(L)
    S = np.nanmean(S)
    print(f'{args.model} on {args.transform} with dataset {args.dataset}:')
    print(f'\t distance {L:.6f} and similarity {S:.6f}')
    logging.info(f'{args.model} on {args.transform} with dataset {args.dataset}:')
    logging.info(f'\t distance {L:.6f} and similarity {S:.6f}')