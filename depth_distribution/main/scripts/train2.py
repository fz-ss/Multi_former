import argparse
import os
import os.path as osp
import pprint
import random
import warnings
import numpy as np
import yaml
import torch
from torch.utils import data
import torch.optim as optim
import sys
sys.path.append('/home/ailab/ailab/SYN/Trans_depth1')
from depth_distribution.main.dataset.cityscapes import CityscapesDataSet
import time, itertools
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '2,3'
from depth_distribution.main.dataset.cityscapes import CityscapesDataSet
from depth_distribution.main.dataset.cityscapes import CityscapesDataSet_1
from depth_distribution.main.dataset.mapillary import MapillaryDataSet, MapillaryDataSet_1
from depth_distribution.main.dataset.synthia import SYNTHIADataSetDepth
from depth_distribution.main.model.build import build_feature_extractor, build_classifier, build_adversarial_discriminator_bin,build_adversarial_discriminator_cls
from depth_distribution.main.model.checkpoint import load_checkpoint
from depth_distribution.main.domain_adaptation.train_UDA import train_depdis
from depth_distribution.main.utils.func import split_premodelname

warnings.filterwarnings("ignore")

def main():
    # LOAD ARGS
    args = get_arguments()
    print("Called with args:")
    print(args)
    device = torch.device("cuda")


    expid = args.expid
    if expid == 1:
        from depth_distribution.configs.synthia_to_cityscapes_16cls  import cfg
    elif expid == 2:
        from depth_distribution.configs.synthia_to_cityscapes_7cls  import cfg
    elif expid == 3:
        from depth_distribution.configs.synthia_to_cityscapes_7cls_small  import cfg
    elif expid == 4:
        from depth_distribution.configs.synthia_to_mapillary_7cls  import cfg
    elif expid == 5:
        from depth_distribution.configs.synthia_to_mapillary_7cls_small  import cfg

    BATCH_SIZE_SOURCE =  int(cfg.TRAIN.BATCH_SIZE_SOURCE / 2)
    BATCH_SIZE_TARGET = int(cfg.TRAIN.BATCH_SIZE_TARGET / 2)
    # auto-generate exp name if not specified
    if cfg.EXP_NAME == "":
        cfg.EXP_NAME = f"{cfg.SOURCE}2{cfg.TARGET}_{cfg.TRAIN.MODEL}_{cfg.TRAIN.DA_METHOD}"
    if args.exp_suffix:
        cfg.EXP_NAME += f"_{args.exp_suffix}"

    # auto-generate snapshot path if not specified
    if cfg.TRAIN.SNAPSHOT_DIR == "":
        cfg.TRAIN.SNAPSHOT_DIR = osp.join(cfg.EXP_ROOT_SNAPSHOT, cfg.EXP_NAME)
    os.makedirs(cfg.TRAIN.SNAPSHOT_DIR, exist_ok=True)

    print("Using config:")
    pprint.pprint(cfg)

    # INIT
    _init_fn = None
    # if not args.random_train:
    #     torch.manual_seed(cfg.TRAIN.RANDOM_SEED)
    #     torch.cuda.manual_seed(cfg.TRAIN.RANDOM_SEED)
    #     np.random.seed(cfg.TRAIN.RANDOM_SEED)
    #     random.seed(cfg.TRAIN.RANDOM_SEED)

    #     def _init_fn(worker_id):
    #         np.random.seed(cfg.TRAIN.RANDOM_SEED + worker_id)

    # # LOAD SEGMENTATION NET
    # assert osp.exists(cfg.TRAIN.RESTORE_FROM), f"Missing init model {cfg.TRAIN.RESTORE_FROM}"

    iternum = 0

    if cfg.TRAIN.MODEL == "Swin_S":
        # FEATURE_EXTRACTOR NETWORK
        feature_extractor = build_feature_extractor(cfg)
        feature_extractor.init_weights()
        load_checkpoint(feature_extractor, cfg.WEIGHTS, strict=False)
        # CLASSIFIER NETWORK
        classifier ,aux = build_classifier(cfg)
        classifier.init_weights()
        aux.init_weights()
        # DISCRIMINATOR NETWORK

        if cfg.SOLVER.DIS == 'binary':
            model_D = build_adversarial_discriminator_bin(cfg)
        else:
            model_D = build_adversarial_discriminator_cls(cfg)
        model_Dis = build_adversarial_discriminator_bin(cfg)

    else:
        raise NotImplementedError(f"Not yet supported {cfg.TRAIN.MODEL}")

    feature_extractor.train()
    feature_extractor.to(device)
    classifier.train()
    classifier.to(device)
    model_D.train()
    model_D.to(device)
    model_Dis.train()
    model_Dis.to(device)

    # feature_extractor's optimizer
    optimizer_fea = torch.optim.AdamW(
        feature_extractor.parameters(), 
        lr=cfg.SOLVER.BASE_LR, 
        betas=(0.9, 0.999), 
        weight_decay=0.01)
    # classifier's optimizer
    optimizer_cls = torch.optim.AdamW(
        itertools.chain(classifier.parameters(),aux.parameters()), 
        lr=cfg.SOLVER.BASE_LR, 
        betas=(0.9, 0.999), 
        weight_decay=0.01)
    
    # discriminators' optimizers
    optimizer_D = torch.optim.Adam(
        itertools.chain(model_D.parameters(), model_Dis.parameters()), 
        lr=cfg.SOLVER.BASE_LR_D, 
        betas=(0.9, 0.99))    



    iternum1 = int(iternum / cfg.NUM_WORKERS)

    # DATALOADERS
    source_dataset = SYNTHIADataSetDepth(
        root=cfg.DATA_DIRECTORY_SOURCE,
        list_path=cfg.DATA_LIST_SOURCE,
        set=cfg.TRAIN.SET_SOURCE,
        num_classes=cfg.NUM_CLASSES,
        max_iters=cfg.TRAIN.MAX_ITERS * BATCH_SIZE_SOURCE,
        crop_size=cfg.TRAIN.INPUT_SIZE_SOURCE,
        mean=cfg.TRAIN.IMG_MEAN,
        iternum=iternum1,
        use_depth=cfg.USE_DEPTH,
        expid = expid
    )
    source_loader = data.DataLoader(
        source_dataset,
        batch_size=BATCH_SIZE_SOURCE,
        num_workers=cfg.NUM_WORKERS,
        shuffle=True,
        pin_memory=True,
        worker_init_fn=_init_fn,
    )


    if cfg.TARGET == 'Cityscapes':
        target_dataset = CityscapesDataSet(
            root=cfg.DATA_DIRECTORY_TARGET,
            list_path=cfg.DATA_LIST_TARGET,
            set=cfg.TRAIN.SET_TARGET,
            info_path=cfg.TRAIN.INFO_TARGET,
            max_iters=cfg.TRAIN.MAX_ITERS * BATCH_SIZE_TARGET,
            crop_size=cfg.TRAIN.INPUT_SIZE_TARGET,
            mean=cfg.TRAIN.IMG_MEAN,
            iternum=iternum1,
        )
    elif cfg.TARGET == 'Mapillary':
        target_dataset = MapillaryDataSet(
            root=cfg.DATA_DIRECTORY_TARGET,
            list_path=cfg.DATA_LIST_TARGET,
            set=cfg.TRAIN.SET_TARGET,
            info_path=cfg.TRAIN.INFO_TARGET,
            max_iters=cfg.TRAIN.MAX_ITERS * BATCH_SIZE_TARGET,
            crop_size=cfg.TRAIN.INPUT_SIZE_TARGET,
            mean=cfg.TRAIN.IMG_MEAN,
            scale_label=True,
            iternum=iternum1
        )
    else:
        raise NotImplementedError(f"Not yet supported dataset {cfg.TARGET}")

    target_loader = data.DataLoader(
        target_dataset,
        batch_size=BATCH_SIZE_TARGET,
        num_workers=cfg.NUM_WORKERS,
        shuffle=True,
        pin_memory=True,
        worker_init_fn=_init_fn,
    )

    if cfg.TARGET == 'Cityscapes':
        test_dataset = CityscapesDataSet_1(
            root=cfg.DATA_DIRECTORY_TARGET,
            list_path=cfg.DATA_LIST_TARGET,
            set=cfg.TEST.SET_TARGET,
            info_path=cfg.TEST.INFO_TARGET,
            crop_size=cfg.TEST.INPUT_SIZE_TARGET,
            mean=cfg.TEST.IMG_MEAN,
            labels_size=cfg.TEST.OUTPUT_SIZE_TARGET,
        )
    elif cfg.TARGET == 'Mapillary':
        test_dataset = MapillaryDataSet_1(
            root=cfg.DATA_DIRECTORY_TARGET,
            list_path=cfg.DATA_LIST_TARGET,
            set=cfg.TEST.SET_TARGET,
            info_path=cfg.TEST.INFO_TARGET,
            crop_size=cfg.TEST.INPUT_SIZE_TARGET,
            mean=cfg.TRAIN.IMG_MEAN,
            scale_label=True
        )
    test_loader = data.DataLoader(
        test_dataset,
        batch_size=cfg.TEST.BATCH_SIZE_TARGET,
        num_workers=cfg.NUM_WORKERS,
        shuffle=False,
        pin_memory=True,
    )

    with open(osp.join(cfg.TRAIN.SNAPSHOT_DIR, "train_cfg.yml"), "w") as yaml_file:
        yaml.dump(cfg, yaml_file, default_flow_style=False)

    train_depdis(feature_extractor,classifier,aux, model_D,model_Dis, optimizer_fea,optimizer_cls, optimizer_D, source_loader, target_loader,test_loader, cfg, expid, iternum)

def get_arguments():
    """
    Parse input arguments
    """
    parser = argparse.ArgumentParser(description="Code for domain adaptation training")
    '''expid
    Syn_City_16cls ---> 1
    Syn_City_7cls ---> 2
    Syn_City_7cls_small ---> 3
    Syn_Map_7cls ---> 4
    Syn_Map_7cls_small ---> 5
    
    '''
    parser.add_argument("--local_rank", type=int, default=0)
    parser.add_argument('--expid', type=int, default=1, help='experiment id')
    parser.add_argument("--random-train", action="store_true", help="not fixing random seed.")
    parser.add_argument("--pret-model", type=str, default='', help="pretrained weights to be used for initialization")
    parser.add_argument("--exp-suffix", type=str, default=None, help="optional experiment suffix")
    return parser.parse_args()

if __name__ == "__main__":
    main()