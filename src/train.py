import logging
import numpy as np
import os
import re
import time
from glob import glob
from PIL import Image
from src.plots import plot_loss, plot_auc, plot_pfe
from src.utils import compute_eer
from src.evaluation.compute_frame_roc_auc import compute_frame_roc_auc
from src.evaluation.compute_pixel_roc_auc import compute_pixel_roc_auc
from sklearn.metrics import roc_auc_score, roc_curve


def train(data, model, num_iteration, data_dir, ext, frame_gt_path, result_path, model_path, print_every=200):
    logging.info("Start training the network: {}".format(time.asctime(time.localtime(time.time()))))
    frame_aucs, frame_eers, pixel_aucs, pixel_eers, losses, valid_losses = [], [], [], [], [], []
    best_auc = 0
    for i in range(num_iteration + 1):
        tr_batch = data.get_train_batch()
        loss = model.batch_train(tr_batch)
        losses.append(loss)
        if i % print_every == 0:
            logging.info("average training reconstruction loss over {0:d} iterations: {1:g}"
                         .format(print_every, np.mean(losses[-print_every:])))
            frame_auc, frame_eer, valid_loss = test(data, model, data_dir, ext, frame_gt_path, result_path)
            logging.info("frame level area under the roc curve at iteration {0:d}: {1:g}".format(i, frame_auc))
            logging.info("un-regularized validation loss at iteration {0:d}: {1:g}".format(i, valid_loss))
            frame_aucs.append(frame_auc), frame_eers.append(frame_eer)
            valid_losses.append(valid_loss)
            if best_auc < frame_auc:
                best_auc = frame_auc
                model.save_model(model_path)
    np.save(os.path.join(result_path, "frame_aucs.npy"), frame_aucs)
    np.save(os.path.join(result_path, "pixel_aucs.npy"), pixel_aucs)
    plot_loss(losses=losses, valid_losses=valid_losses, path=result_path)
    plot_auc(aucs=frame_aucs, path=result_path, level='Frame')
    plot_auc(aucs=pixel_aucs, path=result_path, level='Pixel')
    # store best AUC model and results
    model.restore_model(model_path)
    frame_auc, frame_eer, _ = test(data, model, data_dir, ext, frame_gt_path, result_path, last=True)
    return frame_auc, frame_eer


def test(data, model, data_dir, ext, frame_gt_path, result_path, last=False):
    test_dir = os.path.join(data_dir, 'Test')
    dataset_name = test_dir.split('/')[-2].lower()
    dirs = sorted([os.path.join(test_dir, d) for d in os.listdir(test_dir) if re.match(r'Test[0-9][0-9][0-9]$', d)])
    anom_scores_dir = os.path.join(result_path, 'anomaly_scores')
    if not os.path.exists(anom_scores_dir):
        os.makedirs(anom_scores_dir)
    per_frame_error = [[] for _ in range(len(dirs))]
    seq_idx, f_idx = 0, 0
    min_as, max_as = np.inf, -np.inf
    while True:
        test_batch = data.get_test_batch()
        if test_batch is None:  # test set has been exhausted
            break
        fnames = sorted(glob(os.path.join(dirs[seq_idx], '*.' + ext)))
        # evaluate test batch
        reconstruction, frame_error = model.get_reconstructions(test_batch, is_training=False)
        for i in range(test_batch.shape[0]):
            if f_idx == 0:
                per_frame_error[seq_idx] = [[] for _ in range(len(fnames))]
                im = np.array(Image.open(fnames[f_idx]))
                anom_scores = np.zeros((len(fnames),) + (227, 227), dtype='float32')
                inspection_count = np.zeros(len(fnames), dtype='int')
            for j in range(frame_error[i].shape[0]):
                if last:
                    anom_scores[f_idx + j] += np.square(reconstruction[i, :, :, j] - test_batch[i, :, :, j])
                inspection_count[f_idx + j] += 1
                per_frame_error[seq_idx][f_idx + j].append(frame_error[i, j])
            if f_idx < len(fnames) - data._tvol:
                f_idx += 1
            else:
                seq_idx += 1
                if len(dirs) < seq_idx:
                    fnames = sorted(glob(os.path.join(dirs[seq_idx], '*.' + ext)))
                f_idx = 0
                assert np.all(0 < inspection_count)
                if last:
                    # save anomaly scores
                    anom_scores = np.transpose(np.transpose(anom_scores, [1, 2, 0]) / inspection_count, [2, 0, 1])
                    anom_scores = np.resize(anom_scores, (anom_scores.shape[0], ) + im.shape)
                    min_as, max_as = min(min_as, np.min(anom_scores)), max(max_as, np.max(anom_scores))
                    np.save(os.path.join(anom_scores_dir, 'anomaly_scores_' + str(seq_idx - 1).zfill(3) +
                                         '_ReconstructionError.npy'), anom_scores)
    test_dir = os.path.join(data_dir, 'Test')
    if frame_gt_path is not None and last:
        compute_frame_roc_auc(test_dir=test_dir, ext=ext, frame_gt_path=frame_gt_path,
                              anom_score_range=(min_as, max_as), dist_name='ReconstructionError',
                              result_path=result_path)
        compute_pixel_roc_auc(test_dir=test_dir, ext=ext, frame_gt_path=frame_gt_path,
                              anom_score_range=(min_as, max_as), dist_name='ReconstructionError',
                              result_path=result_path)

    per_frame_average_error = [np.asarray(map(lambda x: np.mean(x), per_frame_error[i]))
                               for i in range(len(per_frame_error))]
    # frame-level AUC/EER
    # min-max normalize to linearly scale into [0, 1] per video
    abnorm_scores = per_video_normalize(per_frame_average_error)
    labels = []
    frame_gt = np.load(os.path.join(frame_gt_path, 'anomalous_frames_' + dataset_name + '.npy'))
    for i in range(frame_gt.shape[0]):
        labels.extend([1 if j in frame_gt[i] else 0 for j in range(abnorm_scores[i].shape[0])])
    labels = np.array(labels)
    abnorm_scores = np.concatenate(abnorm_scores)
    frame_auc = roc_auc_score(y_true=labels, y_score=abnorm_scores)
    fpr, tpr, thresholds = roc_curve(y_true=labels, y_score=abnorm_scores, pos_label=1)
    frame_eer = compute_eer(far=fpr, frr=1 - tpr)
    per_frame_average_error = np.concatenate(per_frame_average_error)
    valid_loss = np.mean(per_frame_average_error[labels == 0])
    if last:
        plot_pfe(pfe=per_frame_average_error, labels=labels, path=result_path)
        np.save(os.path.join(result_path, "per_frame_errors.npy"), per_frame_average_error)

    return frame_auc, frame_eer, valid_loss


def per_video_normalize(pfe):
    err = [None for _ in range(len(pfe))]
    for i in range(len(pfe)):
        err[i] = (pfe[i] - np.min(pfe[i])) / (np.max(pfe[i]) - np.min(pfe[i]))
    return err
