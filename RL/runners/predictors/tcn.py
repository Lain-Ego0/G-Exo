from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn

class CausalConv1d(nn.Module):
    #只读取当今及过去时序上的一维卷积
    
    def __init__(
        self,
        input_channels: int,
        output_channels: int,
        kernel_size:int,
        dilation: int,#这是卷积核的膨胀率
    ) -> None:
        super().__init__()
        
        self.left_padding = (
            (kernel_size - 1) * dilation
        ) #为什么这么写可以保证卷积读取不到未来数据？
        
        self.conv = nn.Conv1d(
            input_channels,
            output_channels,
            kernel_size,
            dilation = dilation,
            padding = 0,
        )
        
    def forward(
        self,
        inputs: torch.Tensor,
    ) -> torch.Tensor:
        padded = F.pad(
            inputs,
            (self.left_padding, 0),
        )
        
        return self.conv(padded)
    
class ResidualBlock(nn.Module):
    #因果卷积残差块
    def __init__(
        self,
        input_channels: int,
        output_channels: int,
        dilation: int,
        *,
        kernel_size: int = 3,
        dropout: float = 0.1, # dropout，随机丢弃，防止过拟合
    ) -> None:
        super().__init__()
        
        self.conv = CausalConv1d(
            input_channels,
            output_channels,
            kernel_size,
            dilation,
        )
        
        self.activation = nn.ReLU()
        self.dropout = nn.Dropout(dropout)
        
        if input_channels != output_channels:
            self.residual = nn.Conv1d(
                input_channels,
                output_channels,
                kernel_size=1,
            )
        else:
            self.residual = nn.Identity()
            
    def forward(
        self,
        inputs: torch.Tensor,
    ) -> torch.Tensor:
        #残差输出
        hidden = self.conv(inputs)
        hidden = self.activation(hidden)
        hidden = self.dropout(hidden)
        
        output = hidden + self.residual(inputs)
        
        return self.activation(output)
    
class MotionTCN(nn.Module):
    
    def __init__(
        self,
        input_dim: int = 32,
        hidden_dim: int = 64,
        target_dim:int = 12,
        horizon_count: int = 2,
        dropout: float = 0.1,
        auxiliary_dim: int = 0,
    ) -> None:
        super().__init__()
        
        self.input_dim = input_dim
        self.target_dim = target_dim
        self.horizon_count = horizon_count
        self.auxiliary_dim = auxiliary_dim
        
        dilations = (1,2,4,8,16)
        blocks = []
        current_channels = input_dim
        
        for dilation in dilations:
            blocks.append(
                ResidualBlock(
                    current_channels,
                    hidden_dim,
                    dilation,
                    dropout=dropout,
                )
            )
            current_channels = hidden_dim
            
        self.encoder = nn.Sequential(*blocks)
        
        self.prediction_head = nn.Linear(
            hidden_dim,
            horizon_count * target_dim,
        )
        self.auxiliary_head = (
            nn.Linear(
                hidden_dim,
                horizon_count * auxiliary_dim,
            )
            if auxiliary_dim > 0
            else None
        )
        
    def encode(
        self,
        inputs: torch.Tensor,
    ) -> torch.Tensor:
        #编码器，将输入数据编码为隐藏状态
        
        if inputs.dim() != 3:
            raise ValueError(
                "TCN input must have shape "
                "[batch, channels, time]."
            )
            
        if inputs.shape[1] != self.input_dim:
            raise ValueError(
                f"Expected {self.input_dim} input channels, "
                f"got {inputs.shape[1]}."
            )
            
        features = self.encoder(inputs)
        
        return features[:,:,-1]
    
    def forward(
        self,
        inputs: torch.Tensor,
    ) -> torch.Tensor:
        latent = self.encode(inputs)
        
        prediction = self.prediction_head(latent)
        
        return prediction.reshape(
            inputs.shape[0],
            self.horizon_count,
            self.target_dim,
        )

    def forward_with_auxiliary(
        self,
        inputs: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """同时输出运动预测和变速辅助预测。"""

        if self.auxiliary_head is None:
            raise RuntimeError("This MotionTCN has no auxiliary head.")

        latent = self.encode(inputs)
        prediction = self.prediction_head(latent).reshape(
            inputs.shape[0],
            self.horizon_count,
            self.target_dim,
        )
        auxiliary = self.auxiliary_head(latent).reshape(
            inputs.shape[0],
            self.horizon_count,
            self.auxiliary_dim,
        )
        return prediction, auxiliary
        
def masked_mse(
    prediction: torch.Tensor,
    target: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    #计算masked均方误差
    
    if prediction.shape != target.shape:
        raise ValueError(
            "Prediction and target shapes must match."
        )

    if mask.shape != target.shape:
        raise ValueError(
            "Mask and target shapes must match."
        )
        
    weights = mask.to(dtype=prediction.dtype)
    
    squared_error = (prediction - target).square()
    
    return (
        (squared_error * weights).sum()
        / weights.sum().clamp_min(1.0) #clamp_min(1.0)是什么意思
    )
    
def main() -> None:
    #smoke test
    
    model = MotionTCN()
    
    inputs = torch.randn(8, 32, 50)
    targets = torch.randn(8, 2, 12)
    mask = torch.ones_like(
        targets,
        dtype=torch.bool,
    )
    
    predictions = model(inputs)
    loss = masked_mse(
        predictions,
        targets,
        mask,
    )
    
    loss.backward()
    
    parameter_count = sum(
        parameter.numel()
        for parameter in model.parameters()
    )
    
    print("input shape:", tuple(inputs.shape))
    print("prediction shape:", tuple(predictions.shape))
    print("loss:", float(loss.detach()))
    print("parameters:", parameter_count)

if __name__ == "__main__":
    main()
