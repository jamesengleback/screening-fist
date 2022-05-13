import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d



def smooth(df,
           sigma=3,
           axis=-1,
           ):
    cols = df.columns
    idx = df.index
    smth = pd.DataFrame(gaussian_filter1d(df, sigma, axis=axis),
                        index=idx,
                        columns=cols)
    return df

def is_anomaly(norm):
    return False

def diff(norm, baseline):
    return norm.subtract(baseline,
                         axis=0)

def response(_diff):
    a420 = _diff.loc[:,420]
    a390 = _diff.loc[:,390]
    return a420.abs().add(a390.abs())

def c2(v1, c1, v2):
    return (v1 * c1) / v2

def proc(cpd, # Cpd()
         sigma=3,
         ):
    name = cpd.name
    test = cpd.test
    ctrl = cpd.ctrl
    echo_map = cpd.echo_map
    norm = norm_traces(test, ctrl)
    smth = smooth(norm, sigma)
    if not is_anomaly(smth):
        change = diff(smth, smth[list(smth.keys())[0]])
        y = dict(response(change))
        #print(y)
        vol_well_map = dict(zip(echo_map['DestWell'],
                                echo_map['Transfer Volume /nl']))
        x = {i:c2(v1=vol_well_map[i] * 1e-9,    # nl to l
                  c1=10e-3,                     # 10 mM stock
                  v2=40e-6,                     # 40 ul well vol
                  ) / 1e-6                     # M to uM
              for i in vol_well_map}
        print(x)
        print(y)



