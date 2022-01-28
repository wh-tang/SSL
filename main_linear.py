import torch
from torchvision import datasets, transforms
from torch.utils.data import DataLoader
from utils import accuracy
from tqdm import tqdm

from models.simclr_base import SimCLRBase
from models.byol_base import BYOLOnlineBase

import argparse


parser = argparse.ArgumentParser()
parser.add_argument('--model_path', default='saved_models')
parser.add_argument('--model', default='simclr')
parser.add_argument('--arch', default='resnet18')
parser.add_argument('--num-classes', type=int, default=10)
parser.add_argument('--output-dim', type=int, default=128)
parser.add_argument('--disable-cuda', action='store_true')
parser.add_argument('--gpu-index', type=int, default=0)


def main():

    args = parser.parse_args()

    # check if gpu training is available
    if not args.disable_cuda and torch.cuda.is_available():
        args.device = torch.device('cuda')
    else:
        args.device = torch.device('cpu')
        args.gpu_index = -1

    # Load in trained network
    if args.model == "simclr":
        model = SimCLRBase(args.arch, args.output_dim)
    elif args.model == "byol":
        model = BYOLOnlineBase(args.arch, args.output_dim)
    

    # Load in train and test sets
    data_transform = transforms.Compose([
        # can add other data augmentation techniques
        transforms.ToTensor(),
        transforms.Normalize((0.1307,), (0.3081,)) # same parameters as self-supervised
    ])

    train_dataset = datasets.MNIST("./datasets", train=True, transform= data_transform, download=False)
    train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)
    test_dataset = datasets.MNIST("./datasets", train=False, transform = data_transform, download=False)
    test_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)

    ### Training
    optimizer = torch.optim.Adam(model.parameters(), lr=3e-4, weight_decay=0.0008)
    criterion = torch.nn.CrossEntropyLoss().to(device)


    for epoch in range(epochs):
        top1_train_accuracy = 0
        for counter, (x_batch, y_batch) in enumerate(tqdm(train_loader)):
            x_batch = x_batch.to(args.device)
            y_batch = y_batch.to(args.device)

            logits = model(x_batch)
            loss = criterion(logits, y_batch)

            top1 = accuracy(logits, y_batch, topk=(1,))
            top1_train_accuracy += top1[0]

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        top1_train_accuracy /= (counter + 1)

        top1_accuracy = 0
        top5_accuracy = 0

        # Test data
        for counter, (x_batch, y_batch) in enumerate(test_loader):
            x_batch = x_batch.to(args.device)
            y_batch = y_batch.to(args.device)

            logits = model(x_batch)

            top1, top5 = accuracy(logits, y_batch, topk=(1, 5))
            top1_accuracy += top1[0]
            top5_accuracy += top5[0]

        top1_accuracy /= (counter + 1)
        top5_accuracy /= (counter + 1)
        print(f"Epoch {epoch}\tTop1 Train accuracy {top1_train_accuracy.item()}\tTop1 Test accuracy: {top1_accuracy.item()}\tTop5 test acc: {top5_accuracy.item()}")

if __name__ == "__main__":
    pass