import time
import numpy as np
from lclib.util import frameconsumer

x = np.random.uniform(size=(512,512))
f = frameconsumer.FrameWriter()
#f = frameconsumer.FrameWriterProcess()
#f.set_log_level(10)

time.sleep(5)
for i in range(5):
    t = time.time()
    f.open(f'./test_{i}.h5')
    print('open: {0:6.3g}\t'.format(time.time()-t), end='')

    t = time.time()
    for j in range(5):
         f.store(x, {'a':1})
    print('store: {0:6.3g}\t'.format(time.time()-t), end='')

    t = time.time()
    f.close()
    print('close: {0:6.3g}'.format(time.time()-t))

    time.sleep(.5)

input('hit enter to finish')
