#!/bin/bash
#SBATCH --gres=gpu:1
#SBATCH --output=/vol/bitbucket/g21mscprj03/SSL/out/linear/%j.out


export PATH=/vol/bitbucket/g21mscprj03/sslvenv/bin/:$PATH
source activate
source /vol/cuda/11.0.3-cudnn8.0.5.39/setup.sh
TERM=vt100  # TERM=xterm
/usr/bin/nvidia-smi
uptime

cd /vol/bitbucket/g21mscprj03/SSL

dset=chexpert
python linear.py -d $dset -m mimic-chexpert_lr_1.0 --batch-size 16
