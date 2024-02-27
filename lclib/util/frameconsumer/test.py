import time
import numpy as np
from lclib import frameconsumer

x = np.random.uniform(size=(512,512))
f = frameconsumer.FrameWriter()
#f = frameconsumer.FrameWriterProcess()

time.sleep(5)
for i in range(5):
    t = time.time(); f.open(f'./test_{i}.h5'); print(time.time()-t)
    t = time.time(); f.store(x, {'a':1}); print(time.time()-t)
    t = time.time(); f.close(); print(time.time()-t)
    time.sleep(.5)

input('hit enter to finish')