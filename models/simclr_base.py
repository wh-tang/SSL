import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision 

from models.conv_net import ConvNet

class SimCLRBase(nn.Module):

    def __init__(self, output_dim, arch='simple'):
        super().__init__()

        # encoder f()
        if arch == 'simple':
            self.encoder = ConvNet()

        # projection head
        dim_proj_head = self.encoder.fc.out_features
        self.projection_head = ProjectionHead(dim_proj_head, output_dim)
    

    def forward(self, x):
        
        h = self.encoder(x)
        z = self.projection_head(h)
        return z


class ProjectionHead(nn.Module):
    
    def __init__(self, input_dim, output_dim, hidden_dim=128):
        super().__init__()
        self.output_dim = output_dim
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim

        self.model = nn.Sequential(
            nn.Linear(self.input_dim, self.hidden_dim),
            nn.ReLU(),
            nn.Linear(self.hidden_dim, self.output_dim))

    def forward(self, x):
        x = self.model(x)
        return F.normalize(x, dim=1)


if __name__ == "__main__":
    model = SimCLRBase(output_dim=10)
    state_dict = model.state_dict()
    torch.save({'state_dict': state_dict}, 'test.pth.tar')
    checkpoint = torch.load('test.pth.tar')
    new_model = SimCLRBase(output_dim=10)
    new_model.load_state_dict(checkpoint['state_dict'])