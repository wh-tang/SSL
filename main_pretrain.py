import argparse

import torch
from methods.byol import BYOLTrainer
from torchvision import transforms, datasets, models
from torch.utils.data import DataLoader, random_split

import numpy as np
import os

from models.simclr_base import SimCLRBase
from models.byol_base import BYOLBase
from methods.simclr import SimCLRTrainer
from data.get_data import DatasetGetter



arch_choices = [name for name in models.__dict__
                      if name.islower() and not name.startswith("__")
                      and callable(models.__dict__[name])]

arch_choices.append("ConvNet")

parser = argparse.ArgumentParser()
parser.add_argument('--method', '-m', default='byol', help='type of ssl pretraining technique')
parser.add_argument('--data-path', default='./datasets', help='path to dataset')
parser.add_argument('--dataset-name', default='MNIST', help='dataset name')
parser.add_argument('-a', '--arch', default='ConvNet', choices=arch_choices)
parser.add_argument('--epochs', default=1, type=int)
parser.add_argument('--batch-size', type=int, default=256)
parser.add_argument('--lr', type=float, default=3e-4)
parser.add_argument('--weight-decay', type=float, default=1e-4)
parser.add_argument('--output-dim', type=int, default=128)
parser.add_argument('--temperature', type=float, default=0.5)
parser.add_argument('--n-views', type=int, default=2)
parser.add_argument('--outpath', default='saved_models')
parser.add_argument('--disable-cuda', action='store_true')
parser.add_argument('--gpu-index', type=int, default=0)

def main():

    args = parser.parse_args()

    # create output directory for pretrained model
    if not os.path.isdir(args.outpath):
        os.makedirs(args.outpath)

    # check if gpu training is available
    if not args.disable_cuda and torch.cuda.is_available():
        args.device = torch.device('cuda')
    else:
        args.device = torch.device('cpu')
        args.gpu_index = -1

    # load data
    pretrain_dataset = DatasetGetter(pretrain=True, train=True, args=args).load()
    pretrain_loader = DataLoader(pretrain_dataset, batch_size=args.batch_size, shuffle=True, drop_last=True)

    # apply ssl pretraining
    if args.method == "simclr":

        model = SimCLRBase(arch=args.arch)
        optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=len(pretrain_loader), eta_min=0, last_epoch=-1)

        with torch.cuda.device(args.gpu_index):
            simclr = SimCLRTrainer(model=model, optimizer=optimizer, scheduler=scheduler, args=args)
            simclr.train(pretrain_loader)

    elif args.method == "byol":

        model = BYOLBase(arch=args.arch)
        optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=len(pretrain_loader), eta_min=0, last_epoch=-1)

        with torch.cuda.device(args.gpu_index):
            byol = BYOLTrainer(model=model, optimizer=optimizer, scheduler=scheduler, args=args)
            print("BYOL is training")
            byol.train(pretrain_loader)
            


if __name__ == "__main__":
    main()