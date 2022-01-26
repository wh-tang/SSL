import torch
import torch.nn as nn
import torch.nn.functional as F

from torch.utils.tensorboard import SummaryWriter
from models.byol_base import BYOLBase, BYOLOnlineBase

from tqdm import tqdm
import logging
import os

# Exponential Moving Average
class EMA():
    def __init__(self, tau):
        super().__init__()
        self.tau = tau

    def update_average(self, old, new):
        if old is None:
            return new
        return old * self.tau + (1 - self.tau) * new



class BYOLTrainer:

    def __init__(self, *args, **kwargs):
        self.args = kwargs['args']
        #self.model = kwargs['model']                # we want the model to be the online network
        self.optimizer = kwargs['optimizer']
        self.scheduler = kwargs['scheduler']
        self.writer = SummaryWriter()

        # the output_dim should be a hyperparameter (change parser)
        self.target_net = BYOLBase(output_dim=256)
        self.model = BYOLOnlineBase(output_dim=256)

        # logging.basicConfig(level=logging.DEBUG)
        logging.basicConfig(filename=os.path.join(self.writer.log_dir, 'training.log'), level=logging.DEBUG)

    def loss_fn(self, q_online, z_target):
        """
        Add in doc strings
        Equation  (2) in BYOL paper
        """
        q_online = F.normalize(q_online, dim=-1, p=2)
        z_target = F.normalize(z_target, dim=-1, p=2)
        return 2 - 2 * (q_online * z_target).sum(dim=-1)

    def update_moving_average(self, ema_updater, ma_model, current_model):
        for current_params, ma_params in zip(current_model.parameters(), ma_model.parameters()):
            old_weight, up_weight = ma_params.data, current_params.data
            ma_params.data = ema_updater.update_average(old_weight, up_weight)

    
    def train(self, train_loader):

        n_iterations = 0
        logging.info(f"Starting BYOL training for {self.args.epochs} epochs.")

        for epoch in range(self.args.epochs):
            print("Epoch:", epoch)
            running_loss = 0 # keep track of loss per epoch

            for batch in tqdm(train_loader):
                
                (v1, v2), y = batch

                # forward pass
                q_online = self.model(v1)
                z_target = self.target_net(v2)

                symmetric_q_online = self.model(v2)
                symmetric_z_target = self.target_net(v1)

                # loss
                loss = self.loss_fn(q_online, z_target)
                symmetric_loss = self.loss_fn(symmetric_q_online, symmetric_z_target)

                byol_loss = loss + symmetric_loss

                # backprop
                self.optimizer.zero_grad()
                byol_loss.backward()
                self.optimizer.step()

                print(self.target_net.parameters())

                n_iterations += 1
                running_loss += loss.item()

            # Scheduler for optimiser - e.g. cosine annealing
            if epoch >= 10:
                self.scheduler.step() 

            training_loss = running_loss/len(train_loader)
            print("Train Loss:", training_loss)
            logging.debug(f"Epoch: {epoch}\tLoss: {training_loss}")

        logging.info("Finished training.")       

        # Save model
        checkpoint_name = 'ssl_{self.args.dataset_name}_trained_model.pth.tar'
        checkpoint_filepath = os.path.join(self.args.outpath, checkpoint_name)
        torch.save( 
                {
                'epoch': self.args.epochs,
                'arch': self.args.arch, 
                'model_state_dict': self.model.state_dict(),
                'optimizer_state_dict': self.optimizer.state_dict()
                }, checkpoint_filepath)

        logging.info(f"Model has been saved at {self.args.outpath}.")


