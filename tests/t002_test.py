import sys
sys.path.insert(0, '..')
import os
import numpy as np
import matplotlib.pyplot as plt

def test_contour2shp():
    from GISops import contour2shp

    # make a quick and dirty Theim solution of drawdown
    X, Y = np.meshgrid(range(10), range(10))
    def dist(x1, y1, x2, y2):
        return np.sqrt((x2-x1)**2+(y2-y1)**2)

    def s(x1, y1, x2, y2):
        return np.log(100/dist(x1, y1, x2, y2)) / (2 * np.pi)

    S = np.reshape([s(x, y, 4.5, 4.5) for x, y in zip(X.ravel(), Y.ravel())], (10, 10))
    levels = [0.5, 0.6, 0.7]
    ctr = plt.contour(S, levels=levels)

    contour2shp(ctr, 'temp/ctr.shp', add_fields={'stuff': ['level1', 'level2', 'level3']})

if __name__ == '__main__':
    if not os.path.isdir('temp'):
        os.makedirs('temp')
    test_contour2shp()
