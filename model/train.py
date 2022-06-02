#!/usr/bin/env python
import os
import argparse
from tqdm import tqdm
import json
from pprint import pprint

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split
from torch import Tensor, cat, mean
from einops import rearrange, repeat
import wandb
from sklearn.metrics import confusion_matrix, precision_recall_curve, roc_curve, det_curve, average_precision_score

from data import Data, DataTensors
from model import Model, Esm, Head, Fpnn, SeqPool

def train(model, 
          data_loader, 
          epochs=8,
          lr=1e-6,
          #loss_fn='cross_entropy',
          proc=False,
          n_non_binders=0,
          save_path=None,
          cuda=False,
          test=False,
          test_loader=None,
          **kwargs,
          ):
    #assert loss_fn in {'cross_entropy'}
    weight=Tensor([1.]*data_loader.batch_size \
                         + [0.]*data_loader.batch_size * n_non_binders)
    loss_fn = nn.BCELoss()#weight=weight)

    opt = torch.optim.Adam(model.parameters(), 
                           lr=lr,
                           )
    for epoch in range(epochs):
        # todo - data_loader sampler: importance sampling
        with tqdm(data_loader) as bar:
            for i, (seq_, fingerprints_, hit_) in enumerate(bar):
                if cuda:
                    seq_, fingerprints_, hit_ = seq_.cuda(), fingerprints_.cuda(), hit_.cuda()
                seq = rearrange(seq_, 'b1 b2 l -> (b1 b2) l')
                fingerprints = rearrange(fingerprints_, 'b1 b2 l -> (b1 b2) l')
                hit = rearrange(hit_, 'b1 b2 -> (b1 b2)')
                yh = model(seq, fingerprints) # seq should be repeats, does it cache?
                if len(hit.shape) == 1:
                    y = rearrange(hit.float(), '(b c) -> b c', c=1)
                else:
                    y = hit.float()
                #print({'seq':seq.shape, 'fingerprints':fingerprints.shape, 'hit':hit.shape,
                #    'yh':yh.shape, 'y':y.shape})
                loss = loss_fn(yh, y)
                loss.backward()
                opt.step()
                opt.zero_grad()

                bar.set_postfix({'epoch':epoch,
                                 'loss':loss.detach().item(),
                                 })
                if not args.test:
                    wandb.log({'loss':loss.detach().cpu().item(), })
                wandb.log({'epoch':epoch,
                          'loss':loss.detach().cpu().item(),
                           })
                if i % 2048 == 0:
                    if save_path is not None:
                        torch.save(model.state_dict(), 
                                   os.path.join(save_path, 
           f"{save_path.split('/')[-1]}_e{epoch}i{int(i/2048)}l{round(loss.cpu().detach().item(), 4)}.pt"
            if save_path is not None:
                torch.save(model.state_dict(), 
                           os.path.join(save_path, 
   f"{save_path.split('/')[-1]}_e{epoch}l{round(loss.cpu().detach().item(), 4)}.pt"
                                       )
                               )
                                               )
                                   )
        #if test_loader is not None:
        #    if epoch % 2 == 0:
        #        test(test_loader,
        #             model,
        #             cuda=cuda,
        #             save_path=save_path,
        #             )

def test(data_loader,
         model,
         cuda=False,
         n_non_binders=1,
         save_path=None,
         ):
    losses, ys, yhs = [], [], []
    with model.eval():
        for seq_, fingerprints_, hit_ in tqdm(data_loader):
            if cuda:
                seq_, fingerprints_, hit_ = seq_.cuda(), fingerprints_.cuda(), hit_.cuda()
            seq = rearrange(seq_, 'b1 b2 l -> (b1 b2) l')
            fingerprints = rearrange(fingerprints_, 'b1 b2 l -> (b1 b2) l')
            hit = rearrange(hit_, 'b1 b2 -> (b1 b2)')
            yh = model(seq, fingerprints)
            if len(hit.shape) == 1:
                y = rearrange(hit.float(), '(b c) -> b c', c=1)
            else:
                y = hit.float()
            loss = loss_fn(yh, y)
            losses.append(loss.reshape(-1).detach())
            ys.append(y.reshape(-1).detach())
            yhs.append(yh.reshape(-1).detach())
    losses = cat(losses)
    mean_loss = mean(losses).to_numpy()
    yhs = cat(yhs).to_numpy()
    ys = cat(ys).to_numpy()

    cfz = confusion_matrix(ys, yhs)
    tn, fp, fn, tp = cfz
    precision, recall, pr_thresholds = precision_recall_curve(ys, yhs)
    fpr, tpr, roc_thresholds = roc_curve(ys, yhs)
    det = det_curve(ys, yhs)
    d = {'mean_loss':mean_loss,
         'average_precision_score':avpr,
         'confusion_matrix':{'true_pos':tp,
                             'true_neg':tn
                             'false_pos':fp,
                             'false_neg':fn,
                             },
         'roc':{'false_pos':fpr,
                'true_pos':tpr,
                'roc_thresholds':roc_thresholds,
                }
         'det':det,
         }
    with open(os.path.join(save_path, 'test.json')) as f:
        json.dump(d, f)

def main(args):
               
    data = DataTensors(args.input, 
                       test=args.test, 
                       n_non_binders=3)
    #data = Data(args.input, test=True)
    a = len(data) // 4
    train_data, test_data = random_split(data, (len(data)-a, a))
    train_loader = DataLoader(train_data,
                              batch_size=args.batch_size,
                              shuffle=True,
                              num_workers=1,
                              )
    test_loader = DataLoader(test_data,
                             batch_size=args.batch_size,
                             shuffle=True,
                             num_workers=1,
                             )

    model = Model(esm=Esm(model=args.esm),
                  seqpool=SeqPool(conv_channels=35,
                                  num_conv_layers=args.num_conv_layers_pool,
                                  kernel_size=args.kernel_size_pool,
                                  stride=args.stride_pool,
                                  num_lstm_layers=args.num_lstm_layers_pool,
                                  lstm_hs=args.lstm_hs_pool,
                                  ),
                  fpnn=Fpnn(fp_size=2048,
                            emb_size=args.emb_size_fp,
                            n_layers=args.n_layers_fp,
                            ),
                  head=Head(emb_size=args.emb_size_head,
                            n_layers=args.n_layers_head,
                            )
                  )
    if args.cuda:
        model = model.cuda()

    if not args.test:
        run = wandb.init(project='sxfst', config=args)
        run_name = run.name
        wandb.watch(model)
    else:
        run_name = 'test'
    save_path = os.path.join('weights', run_name)
    if not os.path.exists(save_path):
        os.makedirs(save_path)

    train(model,
          train_loader,
          proc=False,
          n_non_binders=1,
          lr=args.lr,
          epochs=args.epochs,
          save_path=save_path,
          cuda=args.cuda,
          test=args.test,
          )

    test(model,
         test_loader,
         n_non_binders=1,
         cuda=args.cuda,
         save_path=save_path,
         )

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input')
    parser.add_argument('-b', '--batch_size', default=2, type=int)
    parser.add_argument('-e', '--epochs', default=8, type=int)
    parser.add_argument('-l', '--lr', default=1e-6, type=float)
    parser.add_argument('--esm', default='esm1_t6_43M_UR50S')
    parser.add_argument('--cuda', action='store_true')
    parser.add_argument('--wandb', action='store_true')
    parser.add_argument('--test', action='store_true')
    # Head
    parser.add_argument('--emb_size_head', default=192, type=int)
    parser.add_argument('--n_layers_head', default=4, type=int)
    # Fpnn
    parser.add_argument('--emb_size_fp', default=128, type=int)
    parser.add_argument('--n_layers_fp', default=3, type=int)
    # SeqPool
    parser.add_argument('--num_conv_layers_pool', default=2, type=int)
    parser.add_argument('--num_lstm_layers_pool', default=2, type=int)
    parser.add_argument('--kernel_size_pool', default=9, type=int)
    parser.add_argument('--stride_pool', default=3, type=int)
    parser.add_argument('--lstm_hs_pool', default=32, type=int)
    args = parser.parse_args()
    assert args.input is not None
    assert os.path.isfile(args.input)
    main(args)
