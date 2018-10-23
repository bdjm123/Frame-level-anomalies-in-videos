from __future__ import print_function, division
from src.spatial_temporal_autoencoder import SpatialTemporalAutoencoder
from src.data_iterator_new import DataIteratorNormal, DataIteratorStae
from src.conv_AE_2D import ConvAE2d
from src.experiment import Experiment
import ConfigParser
import logging
import os
import time
import datetime
from src.train import train


if __name__ == "__main__":
    Config = ConfigParser.ConfigParser()
    config_path = os.path.join("config", "config.ini")
    Config.read(config_path)
    NUM_ITER = int(Config.get("Default", "NUM_ITER"))
    ALPHA = float(Config.get("Default", "ALPHA"))
    LAMBDA = float(Config.get("Default", "LAMBDA"))
    GAMMA = float(Config.get("Default", "GAMMA"))
    BATCH_SIZE = int(Config.get("Default", "BATCH_SIZE"))
    TVOL = int(Config.get("Default", "TVOL"))
    DATA_DIR = Config.get("Default", "DATA_DIR")
    EXT = Config.get("Default", "EXT")
    FRAME_GT_PATH = Config.get("Default", "FRAME_GT_PATH")
    METHOD = Config.get("Default", "METHOD")

    ts = time.time()
    dt = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
    result_path = os.path.join("results", "archive", METHOD, dt)
    os.makedirs(result_path)
    logging.basicConfig(filename=os.path.join(result_path, "info.log"), level=logging.INFO)
    model_path = os.path.join("models", METHOD, dt)
    os.makedirs(model_path)

    if METHOD == 'STAE':
        net = SpatialTemporalAutoencoder(tvol=TVOL, alpha=ALPHA, lambd=LAMBDA)
        d = DataIteratorStae(data_dir=DATA_DIR, ext=EXT, batch_size=BATCH_SIZE, tvol=TVOL)
    elif METHOD == 'CONVAE2D':
        net = ConvAE2d(tvol=TVOL, alpha=ALPHA, lambd=LAMBDA)
        d = DataIteratorNormal(data_dir=DATA_DIR, ext=EXT, batch_size=BATCH_SIZE, tvol=TVOL)
    elif METHOD == 'EXP':
        net = Experiment(tvol=TVOL, alpha=ALPHA, lambd=LAMBDA)
        d = DataIteratorNormal(data_dir=DATA_DIR, ext=EXT, batch_size=BATCH_SIZE, tvol=TVOL)
    else:
        raise ValueError('Incorrect method specification')

    frame_auc, frame_eer = train(data=d, model=net, num_iteration=NUM_ITER, data_dir=DATA_DIR, ext=EXT,
                                 frame_gt_path=FRAME_GT_PATH, result_path=result_path, model_path=model_path)
    logging.info("Best frame-level area under the roc curve: {0:g}".format(frame_auc))
    logging.info("Frame-level equal error rate corresponding to this: {0:g}".format(frame_eer))
