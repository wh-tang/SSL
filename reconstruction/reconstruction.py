# Use our own models

import numpy as np
from transformers import ImageGPTConfig
import reconstruction.customized_resnet as models # replace this with our own models
import argparse
import os
import torch
import torch.nn as nn

import time
from PIL import Image
from torch.autograd import Variable
import torch.nn.functional as F
from torch import optim
import torchvision.transforms as transforms
from matplotlib import pyplot as plt
from reconstruction.skip import skip

import PIL
from PIL import Image


model_names = sorted(name for name in models.__dict__
    if name.islower() and not name.startswith("__")
    and callable(models.__dict__[name])) # model names supposed to be a list of models we support

parser = argparse.ArgumentParser(description='Deep Image Reconstruction')
parser.add_argument('--data', metavar='DIR', default='./test_img',
                    help='path to dataset')
parser.add_argument('-a', '--arch', metavar='ARCH', default='resnet50',
                    choices=model_names,
                    help='pretrained_model architecture: ' +
                        ' | '.join(model_names) +
                        ' (default: resnet50)')
# I think we have a simpler way of doing this
parser.add_argument('--pretrained', default=['./checkpoints/resnet50-19c8e357.pth'],
                    help='path to res pretrained checkpoint')

parser.add_argument('--input_dir', default = './data/diabetic_retinopathy/train/10_left.jpeg')
parser.add_argument('--output_dir', default=['./result/reconstructed_images/'])

parser.add_argument('--which_layer', default='layer4') # maybe can choose
parser.add_argument('--lr', default=0.001, type=float)
parser.add_argument('--initial_size', default=256, type=int) # ??
parser.add_argument('--img_size', default=224, type=int) # may need to change
parser.add_argument('--max_iter', default=3000, type=int)
parser.add_argument('--ckpt_iter', default=[1000,3000,5000])
parser.add_argument('--device', type=str, default='cuda', help='CUDA or CPU training (cuda | cpu)')

args = parser.parse_args()
if not torch.cuda.is_available():
    args.device = "cpu"

## load pretrained model

# if args.model in ['mimic-chexpert_lr_0.1', 'mimic-chexpert_lr_0.01', 'mimic-chexpert_lr_1.0', 'supervised_d121']:
#     model = DenseNetBackbone(args.model)
#     feature_dim = 1024
# elif 'mimic-cxr' in args.model:
#     if 'r18' in args.model:
#         model = ResNet18Backbone(args.model)
#         feature_dim = 512
#     else:
#         model = DenseNetBackbone(args.model)
#         feature_dim = 1024
# elif args.model == 'supervised_r18':
#     model = ResNet18Backbone(args.model)
#     feature_dim = 512
# else:
#     model = ResNetBackbone(args.model)
#     feature_dim = 2048

#     model = model.to(args.device)


def checkdir(dir):
    if not os.path.exists(dir):
        os.makedirs(dir)
        print('Make dir: %s'%dir)

def fill_noise(x, noise_type):
    """Fills tensor `x` with noise of type `noise_type`."""
    if noise_type == 'u':
        x.uniform_()
    elif noise_type == 'n':
        x.normal_()
    else:
        assert False

    def _tensor_size(self,t):
        return t.size()[1]*t.size()[2]*t.size()[3]

def np_to_torch(img_np):
    '''Converts image in numpy.array to torch.Tensor.
    From C x W x H [0..1] to  C x W x H [0..1]
    '''
    return torch.from_numpy(img_np)[None, :]

def get_noise(input_depth, spatial_size, noise_type='u', var=1. / 10):
    """Returns a pytorch.Tensor of size (1 x `input_depth` x `spatial_size[0]` x `spatial_size[1]`)
    initialized in a specific way.
    Args:
        input_depth: number of channels in the tensor
        spatial_size: spatial size of the tensor to initialize
        noise_type: 'u' for uniform; 'n' for normal
        var: a factor, a noise will be multiplicated by. Basically it is standard deviation scaler.
    """
    if isinstance(spatial_size, int):
        spatial_size = (spatial_size, spatial_size)

    shape = [1, input_depth, spatial_size[0], spatial_size[1]]
    net_input = torch.zeros(shape)

    fill_noise(net_input, noise_type)
    net_input *= var

    return net_input

def postp(tensor): # to clip results in the range [0,1]
    postpa = transforms.Compose([transforms.Normalize(
                                     mean=[-0.485 / 0.229, -0.456 / 0.224, -0.406 / 0.225],
                                     std=[1 / 0.229, 1 / 0.224, 1 / 0.225]),
                                 ])
    postpb = transforms.Compose([transforms.ToPILImage()])

    t = postpa(tensor)
    t[t>1] = 1
    t[t<0] = 0
    img = postpb(t)
    return img

def get_params(opt_over, net, net_input, downsampler=None):
    '''Returns parameters that we want to optimize over.
    Args:
        opt_over: comma separated list, e.g. "net,input" or "net"
        net: network
        net_input: torch.Tensor that stores input `z`
    '''
    opt_over_list = opt_over.split(',')
    params = []

    for opt in opt_over_list:

        if opt == 'net':
            params += [x for x in net.parameters()]
        elif opt == 'down':
            assert downsampler is not None
            params = [x for x in downsampler.parameters()]
        elif opt == 'input':
            net_input.requires_grad = True
            params += [net_input]
        else:
            assert False, 'what is it?'

    return params


def main():
    print("=> Loading pre-trained model '{}'".format(args.arch))

    for dir in args.output_dir:
        checkdir(dir)

    pretrained_model = [models.__dict__[args.arch]() for path in args.pretrained]

    # load from pre-trained, before DistributedDataParallel constructor
    for pi,path in enumerate(args.pretrained):
        if os.path.isfile(path):
            print("=> loading checkpoint '{}'".format(path))
            checkpoint = torch.load(path, map_location="cpu")

            try:
                state_dict = checkpoint['model']
            except:
                try:
                    state_dict = checkpoint['state_dict']
                except:
                    state_dict = checkpoint
            for k in list(state_dict.keys()):
                if k.startswith('fc.'):
                    del state_dict[k]
                elif k.startswith('module.fc.'):
                    del state_dict[k]
                elif k.startswith('module'):
                    state_dict[k.replace('module.','')]=state_dict[k]
                    del state_dict[k]

            args.start_epoch = 0
            msg = pretrained_model[pi].load_state_dict(state_dict, strict=False)
            print(msg.missing_keys)
            if len(msg.missing_keys):
                assert set(msg.missing_keys) == {"fc.weight", "fc.bias"}

            print("=> loaded pre-trained model '{}'".format(path))
        else:
            print("=> no checkpoint found at '{}'".format(path))
        pretrained_model[pi].eval() # to device

    for pi in range(len(args.pretrained)):
        for name, param in pretrained_model[pi].named_parameters():
            param.requires_grad = False

    dir = os.path.join(args.data, 'val')

    # Dataloader
    img = Image.open(args.input_dir)

    # Normalise image
    imsize = 224
    transform = transforms.Compose([
            transforms.Resize(imsize, interpolation=PIL.Image.BICUBIC),
            transforms.CenterCrop(imsize),
            transforms.ToTensor() # do we need normalise
        ])

    img = transform(img)
    img = torch.unsqueeze(img, 0)

    print(img.shape) # (4752, 3168)
    filename = "Reconstructed image" # change this to be the last part of image file name

    criterion = nn.MSELoss().to(args.device)
    input_depth = 32 # need to change?
    imsize_net = 256 # need to change?

    for pi in range(len(args.pretrained)): # loop through different models
        # Forward pass through pretrained models
        targets = pretrained_model[pi].forward(
            img,
            name = args.which_layer
        ).detach()

        out_path = os.path.join(args.output_dir[pi], args.which_layer, filename) # supposed to be a list of filenames

        if not os.path.exists(out_path):
            print(f"Reconstructing Image {filename}")

            start=time.time()

            pad = 'zero'  # 'refection'
            net = skip(input_depth, 3, num_channels_down=[16, 32, 64, 128, 128, 128],
                        num_channels_up=[16, 32, 64, 128, 128, 128],
                        num_channels_skip=[4, 4, 4, 4, 4, 4],
                        filter_size_down=[7, 7, 5, 5, 3, 3], filter_size_up=[7, 7, 5, 5, 3, 3],
                        upsample_mode='nearest', downsample_mode='avg',
                        need_sigmoid=False, pad=pad, act_fun='LeakyReLU').type(img.type())

            net = net.to(args.device)

            net_input = get_noise(input_depth, imsize_net).type(img.type()).detach()
            out = net(net_input)[:, :, :224, :224]

            # Compute number of parameters
            s = sum(np.prod(list(p.size())) for p in net.parameters())
            print('Number of params: %d' % s)

            print("Targets size", targets.shape)

            target = targets # not sure if right
            # target = targets[[img,],...]
            print("Target shape", target.shape)

            # run style transfer
            max_iter = args.max_iter
            show_iter = 50
            optimizer = optim.Adam(get_params('net', net, net_input), lr=args.lr)
            n_iter = [0]

            while n_iter[0] <= max_iter:

                def closure():
                    optimizer.zero_grad()
                    out = pretrained_model[pi].forward(
                        net(net_input)[:, :, :imsize, :imsize], name=args.which_layer)
                    # out gives features from pretrained network when input is noise fed into encoder-decoder network
                    # target is features from pretrained network when input is original image
                    loss = criterion(out, target)
                    loss.backward()
                    n_iter[0] += 1
                    # print loss
                    if n_iter[0] % show_iter == (show_iter - 1):
                        print('Iteration: %d, loss: %f' % (n_iter[0] + 1, loss.item()))
                    return loss

                optimizer.step(closure)

            out_img = postp(net(net_input)[:, :, :imsize, :imsize].data[0].cpu().squeeze())
            # plt.imshow(out_img)
            # plt.show()
            end = time.time()
            print('Time:'+str(end-start))

            checkdir(os.path.dirname(out_path))
            out_img.save(out_path)

        else:
            print("Reconstructed image already exists. Exiting.")

if __name__ == '__main__':
    main()
