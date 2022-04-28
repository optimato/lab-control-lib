# read and output data from the Excillum ".log" files
# The files contain as first line what the entries are, then a line with all entries for each time
import numpy as np
import matplotlib.pyplot as plt

################################################################################
def monitor_log_read(filename):
    #---------------------------------------------------------------------------
    # open file
    with open(filename) as fid:
        # read enttry names
        entry_names_tmp = fid.readline()
        entry_names_tmp = entry_names_tmp.split(',')
        entry_names = [i.strip() for i in entry_names_tmp]
        # read alls subsequent lines
        entry_values = []
        for ind_entry,entry in enumerate(fid):
            # entry_values_tmp = entry.split(',')
            entry_values_tmp = [i.strip() for i in entry.split(',')]
            entry_values.append(entry_values_tmp)
    #---------------------------------------------------------------------------
    # list all possible entries
    print(entry_names)
    # query which entry to pyplot
    entry_to_plot = input('entry to plot:')
    while entry_to_plot not in entry_names:
        print('invalid name')
        entry_to_plot = input('entry to plot:')
    # find the column corresponding to the input
    ind_column = entry_names.index(entry_to_plot)
    # make a vector with all values
    v = np.asarray(entry_values)[:,ind_column]
    #---------------------------------------------------------------------------
    # make a vector containing the time in seconds from beginning of day
    t_tmp = np.asarray(entry_values)[:,0]
    # strip the year and day
    t_tmp = np.asarray([i.split(' ') for i in t_tmp])
    # separate hours, minutes and seconds
    t_tmp = [i.split(':') for i in t_tmp[:,1]]
    # convert to int
    t_tmp = [list(map(int,i)) for i in t_tmp]
    # helper array to convert to seconds
    t_help = np.asarray([3600,60,1])
    # calculate seconds
    t = [sum(i*t_help) for i in t_tmp]
    # check if lasty entry of t is 0, then it belongs to the next day
    # in that case set it to last time + 5...
    if t[-1] == 0:
        t[-1] = t[-2] + 5
    #---------------------------------------------------------------------------
    # check if entry is numeric and can be plotted
    if is_float(entry_values[0][ind_column]):
        # plot against time
        plt.figure(),plt.plot(t,v),plt.show(block=False)
    else:
        print('entry is a string, cant be plotted')

    return entry_names[ind_column],v,t




################################################################################
# little helper function to check if a str is a float
def is_float(a):
    try:
        float(a)
        return True
    except ValueError:
        return False
