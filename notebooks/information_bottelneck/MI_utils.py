import keras
import keras.backend as K
import tensorflow as tf
import numpy as np
from keras import regularizers
from keras.layers.core import Dropout
from tensorflow.keras.layers import Layer
from tensorflow.keras.activations import relu,sigmoid, softmax, tanh
import sys 
sys.path.insert(0, "/content/MI")
import utils
import loggingreporter 
import os
from six.moves import cPickle
from collections import defaultdict, OrderedDict
import kde
import simplebinmi
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec


def compute_MI(cfg, ARCH_NAME, DO_LOWER, DO_BINNED, trn, tst):
    '''
    Function that computes the MI based on the cofiguration of the network and
    the directory the logged data is stored in

    Parameters:
    cfg (dict): configuration of the network
    ARCH_NAME (Sting): name of the directory with the data
    DO_LOWER (Boolean): whether to compute lower
    DO_BINNED (Boolean): whether to compute binned
    trn (Dataset): training dataset
    tst (Dataset): test dataset 

    Returns:
    dict: computed MI
    list: layers to plot

    '''

    FULL_MI           = cfg['FULL_MI']
    infoplane_measure = 'bin'             # What plot do we want to show (could be upper as well)
    DO_SAVE           = True              # Save the plot?
    NUM_LABELS        = 2                  # Just two labels: stroke or no stroke
    COLORBAR_MAX_EPOCHS = cfg['NUM_EPOCHS']# Same as max epochs
    DIR_TEMPLATE      = '%%s_%s'%ARCH_NAME # Name of the directory (based on the network settings)

    # Functions to return upper and lower bounds on entropy of layer activity
    noise_variance = 1e-3                   # Added Gaussian noise variance
    binsize = 0.5                           # size of bins for binning method
    Klayer_activity = K.placeholder(ndim=2) # Keras placeholder 
    entropy_func_upper = K.function([Klayer_activity,], [kde.entropy_estimator_kl(Klayer_activity, noise_variance),])
    entropy_func_lower = K.function([Klayer_activity,], [kde.entropy_estimator_bd(Klayer_activity, noise_variance),])

    # nats to bits conversion factor
    nats2bits = 1.0/np.log(2) 

    # Save indexes of tests data for each of the output classes
    saved_labelixs = {}
    full = utils.construct_full_dataset(trn,tst)
    y = full.y
    Y = full.Y

    for i in range(NUM_LABELS):
        saved_labelixs[i] = y == i

    labelprobs = np.mean(Y, axis=0)

    # Data structure used to store results - activation can also be tanh, softplus or softsign
    activation = 'relu'
    measures = OrderedDict()
    measures[activation] = {}

    # Find directory where the logged data is stored in
    cur_dir = 'rawdata/' + DIR_TEMPLATE % activation
    if not os.path.exists(cur_dir):
        print("Directory %s not found" % cur_dir)
        
    print('Starting to compute MI')

    # Iterate over all epochs
    for epochfile in sorted(os.listdir(cur_dir)):
    
        fname = cur_dir + "/" + epochfile
        with open(fname, 'rb') as f:
            d = cPickle.load(f)

        epoch = d['epoch']

        print("Doing", fname)
        
        # Count layers and add them to a list
        num_layers = len(d['data']['activity_tst'])
        PLOT_LAYERS = []
        for lndx in range(num_layers):
            PLOT_LAYERS.append(lndx)
                
        cepochdata = defaultdict(list)

        # Iterate over all layers
        for lndx in range(num_layers):
            activity = d['data']['activity_tst'][lndx]

            # Compute marginal entropies
            h_upper = entropy_func_upper([activity,])[0]
            if DO_LOWER:
                h_lower = entropy_func_lower([activity,])[0]
                
            # Layer activity given input. This is simply the entropy of the Gaussian noise
            hM_given_X = kde.kde_condentropy(activity, noise_variance)

            # Compute conditional entropies of layer activity given output
            hM_given_Y_upper=0.
            for i in range(NUM_LABELS):
                hcond_upper = entropy_func_upper([activity[saved_labelixs[i],:],])[0]
                hM_given_Y_upper += labelprobs[i] * hcond_upper
                
            if DO_LOWER:
                hM_given_Y_lower=0.
                for i in range(NUM_LABELS):
                    hcond_lower = entropy_func_lower([activity[saved_labelixs[i],:],])[0]
                    hM_given_Y_lower += labelprobs[i] * hcond_lower
                
            cepochdata['MI_XM_upper'].append( nats2bits * (h_upper - hM_given_X) )
            cepochdata['MI_YM_upper'].append( nats2bits * (h_upper - hM_given_Y_upper) )
            cepochdata['H_M_upper'  ].append( nats2bits * h_upper )

            pstr = 'upper: MI(X;M)=%0.3f, MI(Y;M)=%0.3f' % (cepochdata['MI_XM_upper'][-1], cepochdata['MI_YM_upper'][-1])
            if DO_LOWER:  # Compute lower bounds
                cepochdata['MI_XM_lower'].append( nats2bits * (h_lower - hM_given_X) )
                cepochdata['MI_YM_lower'].append( nats2bits * (h_lower - hM_given_Y_lower) )
                cepochdata['H_M_lower'  ].append( nats2bits * h_lower )
                pstr += ' | lower: MI(X;M)=%0.3f, MI(Y;M)=%0.3f' % (cepochdata['MI_XM_lower'][-1], cepochdata['MI_YM_lower'][-1])

            if DO_BINNED: # Compute binned estimates
                binxm, binym = simplebinmi.bin_calc_information2(saved_labelixs, activity, binsize)
                cepochdata['MI_XM_bin'].append( nats2bits * binxm )
                cepochdata['MI_YM_bin'].append( nats2bits * binym )
                pstr += ' | bin: MI(X;M)=%0.3f, MI(Y;M)=%0.3f' % (cepochdata['MI_XM_bin'][-1], cepochdata['MI_YM_bin'][-1])
                        
            print('- Layer %d %s' % (lndx, pstr) )

        measures[activation][epoch] = cepochdata
    
    return measures, PLOT_LAYERS

def print_MI(measures, COLORBAR_MAX_EPOCHS, infoplane_measure, DIR_TEMPLATE, PLOT_LAYERS, ARCH_NAME):
    '''
    Function that prints the mutual information that has been computed before
    
    Parameters:
    measures (dict): computed MI
    COLORBAR_MAX_EPOCHS (Int): Highest epoch to colour
    infoplane_measure (String): Activation function to plot
    DIR_TEMPLATE (String): Template of the directory of the network
    PLOT_LAYERS (list): Layers to plot
    ARCH_NAME (String): Name of the directory

    '''
    max_epoch = max( (max(vals.keys()) if len(vals) else 0) for vals in measures.values())
    sm = plt.cm.ScalarMappable(cmap='gnuplot', norm=plt.Normalize(vmin=0, vmax=COLORBAR_MAX_EPOCHS))
    sm._A = []

    fig = plt.figure(figsize=(12, 8))

    # Iterate over all measures (in our case only one)
    for actndx, (activation, vals) in enumerate(measures.items()):
        epochs = sorted(vals.keys())
        if not len(epochs):
            continue
        #ax = plt.subplot(1, 2, actndx+1)    
        ax = plt.subplot(1, len(measures.items()), actndx+1)

        # plot every epoch seperatly
        for epoch in epochs:
            c = sm.to_rgba(epoch)
            xmvals = np.array(vals[epoch]['MI_XM_'+infoplane_measure])[PLOT_LAYERS]
            ymvals = np.array(vals[epoch]['MI_YM_'+infoplane_measure])[PLOT_LAYERS]

            ax.plot(xmvals, ymvals, c=c, alpha=0.1, zorder=1)
            ax.scatter(xmvals, ymvals, s=20, facecolors=[c for _ in PLOT_LAYERS], edgecolor='none', zorder=2)

        ax.set_ylim([0, 1])
        ax.set_xlim([0, 12])
        ax.set_xlabel('I(X;M)')
        ax.set_ylabel('I(Y;M)')
        ax.set_title(activation)
        
    cbaxes = fig.add_axes([1.0, 0.125, 0.03, 0.8]) 
    plt.colorbar(sm, label='Epoch', cax=cbaxes)
    plt.tight_layout()

   
    plt.savefig('plots/' + DIR_TEMPLATE % ('infoplane_'+ARCH_NAME),bbox_inches='tight')