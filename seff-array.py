from decimal import Decimal
import math
import argparse
import subprocess

# Histogram code (with modifications) from
# https://github.com/Kobold/text_histogram


class MVSD(object):
    # A class that calculates a running Mean / Variance
    # / Standard Deviation
    def __init__(self):
        self.is_started = False
        self.ss = Decimal(0)  # (running) sum of square deviations from mean
        self.m = Decimal(0)  # (running) mean
        self.total_w = Decimal(0)  # weight of items seen

    def add(self, x, w=1):
        """ add another datapoint to the MVSD """
        if not isinstance(x, Decimal):
            x = Decimal(x)
        if not self.is_started:
            self.m = x
            self.ss = Decimal(0)
            self.total_w = w
            self.is_started = True
        else:
            temp_w = self.total_w + w
            self.ss += (self.total_w * w * (x - self.m)*(x - self.m)) / temp_w
            self.m += (x - self.m) / temp_w
            self.total_w = temp_w

    def var(self):
        """ returns variance """
        return self.ss / self.total_w

    def sd(self):
        """ returns standard deviation """
        return math.sqrt(self.var())

    def mean(self):
        """ returns mean """
        return self.m


def median(values):
    """ returns median of all values """
    length = len(values)
    if length % 2:
        median_indices = [length/2]
    else:
        median_indices = [length/2-1, length/2]

    values = sorted(values)
    return sum([values[round(i)] for i in median_indices])/len(median_indices)


def histogram(stream, req_mem=0, req_cpus=0, req_time=0,
              timeflag=False, minimum=None, maximum=None,
              buckets=None, custbuckets=None, calc_msvd=True):
    """
    Loop over the stream and add each entry to the dataset,
    printing out the histogram at the end.
    

    stream: list of data points
    req_mem: requested memory for the job array
    req_cpus: requested cores for the job array
    req_time: requested runtime for the job array
    timeflag: distinguishes between the memory and time histograms
    minimum: minimum value for graph
    maximum: maximum value for graph
    buckets: Number of buckets to use for the histogram
    custbuckets: Comma seperated list of bucket edges for the histogram
    calc_msvd: Calculate and display Mean, Variance and SD.
    """
    if not minimum or not maximum:
        # glob the iterator here so we can do min/max on it
        data = list(stream)
    else:
        data = stream
    bucket_scale = 1

    if minimum:
        min_v = Decimal(minimum)
    else:
        min_v = min(data)
    if maximum:
        max_v = Decimal(maximum)
    else:
        max_v = max(data)

    if not max_v >= min_v:
        raise ValueError('max must be >= min. max:%s min:%s' % (max_v, min_v))

    diff = max_v - min_v
    boundaries = []
    bucket_counts = []

    if custbuckets:
        bound = custbuckets.split(',')
        bound_sort = sorted(map(Decimal, bound))

        # if the last value is smaller than the maximum, replace it
        if bound_sort[-1] < max_v:
            bound_sort[-1] = max_v

        # iterate through the sorted list and append to boundaries
        for x in bound_sort:
            if x >= min_v and x <= max_v:
                boundaries.append(x)
            elif x >= max_v:
                boundaries.append(max_v)
                break

        '''beware: the min_v is not included in the boundaries,
        so no need to do a -1!'''
        bucket_counts = [0 for x in range(len(boundaries))]
        buckets = len(boundaries)
    else:
        buckets = buckets or 10
        if buckets <= 0:
            raise ValueError('# of buckets must be > 0')
        step = diff / buckets
        bucket_counts = [0 for x in range(buckets)]
        for x in range(buckets):
            boundaries.append(min_v + (step * (x + 1)))

        if req_mem:
            # first, parse req_mem to MB, and turn into an int
            if req_mem[-2] == 'G':
                req_mem_int = int(req_mem[:-2]) * 1000
            elif req_mem[-2] == 'K':
                req_mem_int = int(req_mem[:-2]) / 1000
            else:
                req_mem_int = int(req_mem[:-2])

            # then, check if memory was requested per node or per cpu
            if req_mem[-1] == 'c':
                req_mem_int *= int(req_cpus)

            # OPTIONAL STYLE CHOICE:
            # lastly, redo the boundaries so that the maximum
            # of the last bin is the total requested memory
            # boundaries = [(req_mem_int/10)*x  for x in range(1,11)]

    skipped = 0
    samples = 0
    mvsd = MVSD()
    accepted_data = []

    for value in data:
        samples += 1
        if calc_msvd:
            mvsd.add(value)
            accepted_data.append(value)
        # find the bucket this goes in
        if value < min_v or value > max_v:
            skipped += 1
            continue
        for bucket_postion, boundary in enumerate(boundaries):
            if value <= boundary:
                bucket_counts[bucket_postion] += 1
                break

    # auto-pick the hash scale
    if max(bucket_counts) > 60:
        bucket_scale = int(max(bucket_counts) / 60)

    # histograms for time and memory usage are formatted differently
    if timeflag:
        print('========== Elapsed Time ==========')
        print('# NumSamples = %d; Min = %s; Max = %s' %
              (samples, int_to_time(round(min_v)), int_to_time(round(max_v))))
        if skipped:
            print('# %d value%s outside of min/max' %
                  (skipped, skipped > 1 and 's' or ''))
        if calc_msvd:
            print('# Mean = %s; SD = %s; Median %s' %
                  (int_to_time(round(mvsd.mean())),
                   int_to_time(round(mvsd.sd())),
                   int_to_time(round(median(accepted_data)))))

        print('# each ∎ represents a count of %d' % bucket_scale)
        bucket_min = min_v*0.9
        bucket_max = min_v*0.9
        for bucket in range(buckets):
            bucket_min = bucket_max
            bucket_max = boundaries[bucket]
            bucket_count = bucket_counts[bucket]
            star_count = 0
            if bucket_count:
                star_count = bucket_count // bucket_scale
            print('{:10s} - {:10s} [{:4d}]: {}'
                  .format(int_to_time(round(bucket_min)),
                          int_to_time(round(bucket_max)), bucket_count,
                          '∎' * star_count))

        if req_time != 0 and mvsd.mean()*4 <= time_to_int(req_time):
            print('*'*80)
            print('The requested runtime was %s.\
                 \nThe average runtime was %s.\
                 \nRequesting less time would allow jobs to run more quickly.'
                  % (req_time, int_to_time(round(mvsd.mean()))))
            print('*'*80)
        else:
            print('The requested runtime was %s.' % req_time)

    else:
        print('========== Max Memory Usage ==========')
        print('# NumSamples = %d; Min = %0.2f MB; Max = %0.2f MB' %
              (samples, min_v, max_v))
        if skipped:
            print('# %d value%s outside of min/max' %
                  (skipped, skipped > 1 and 's' or ''))
        if calc_msvd:
            print('# Mean = %0.2f MB; Variance = %0.2f MB; \
                  SD = %0.2f MB; Median %0.2f MB' %
                  (mvsd.mean(), mvsd.var(), mvsd.sd(), median(accepted_data)))

        print('# each ∎ represents a count of %d' % bucket_scale)
        bucket_min = min_v*0.9
        bucket_max = min_v*0.9
        for bucket in range(buckets):
            bucket_min = bucket_max
            bucket_max = boundaries[bucket]
            bucket_count = bucket_counts[bucket]
            star_count = 0
            if bucket_count:
                star_count = bucket_count // bucket_scale
            print('%10.4f - %10.4f MB [%4d]: %s' %
                  (bucket_min, bucket_max, bucket_count, '∎' * star_count))
        if req_mem_int/5 >= mvsd.mean():
            print('*'*80)
            print('The requested memory was %sMB. \
                 \nThe average memory usage was %sMB. \
                 \nRequesting less memory would allow \
                   jobs to run more quickly.' %
                  (req_mem_int, round(mvsd.mean())))
            print('*'*80)
        else:
            print('The requested memory was %sMB.' % req_mem_int)


def time_to_int(time):
    """ converts hh:mm:ss time to seconds """
    days = 0
    if '-' in time:
        days = int(time.split('-')[0])*86400
        time = time.split('-')[1]
    time = time.split(':')
    hours = int(time[0])*3600
    mins = int(time[1])*60
    secs = int(time[2])
    return(days+hours+mins+secs)


def int_to_time(secs):
    """ converts seconds to hh:mm:ss """
    hours = 0
    mins = 0

    while secs >= 3600:
        hours += 1
        secs -= 3600
    while secs >= 60:
        mins += 1
        secs -= 60

    hours = str(hours)
    mins = str(mins)
    secs = str(secs)

    if len(hours) < 2:
        hours = '0' + hours
    if len(mins) < 2:
        mins = '0' + mins
    if len(secs) < 2:
        secs = '0' + secs

    return(hours + ':' + mins + ':' + secs)


def main():
    data_collector = {}  # key = job_id; val = [maxRSS, elapsed]
    elapsed_list = []
    maxRSS_list = []

    if arrayID:
        query = 'sacct -p -j %s --format=JobID,JobName,MaxRSS,Elapsed,ReqMem,\
                 ReqCPUS,Timelimit' % arrayID
        result = subprocess.check_output([query], shell=True)
        result = str(result, 'utf-8')
        data = result.split('\n')[1:]

    else:
        with open(inputfile) as f:
            headers = f.readline()
            data = f.readlines()
            f.close()

    req_mem = data[0].split('|')[4]
    req_cpus = data[0].split('|')[5]
    req_time = data[0].split('|')[6]

    for line in data:
        if line == '' or line == '\n':
            continue

        line = line.split('|')
        jobID = line[0].split('.')[0]
        maxRSS = line[2]
        elapsed = line[3]

        if maxRSS == '':
            continue
        if 'K' in maxRSS:
            maxRSS = maxRSS.replace('K', '')
            maxRSS = float(maxRSS)/1000
        elif 'M' in maxRSS:
            maxRSS = maxRSS.replace('M', '')
            maxRSS = float(maxRSS)
        elif 'G' in maxRSS:
            maxRSS = maxRSS.replace('G', '')
            maxRSS = float(maxRSS)*1000

        if jobID not in data_collector.keys():
            data_collector[jobID] = [float(maxRSS), elapsed]
        else:
            data_collector[jobID][0] += float(maxRSS)

    for pair in data_collector.values():
        maxRSS_list.append(pair[0])
        elapsed_list.append(pair[1])

    # single job handling
    if len(maxRSS_list) == 1:
        print('======Job ID: %s======' % list(data_collector)[0])
        print('Memory Usage: %sMB' % maxRSS_list[0])
        print('Requested Memory: %s' %
              req_mem.replace('c', 'B').replace('n', 'B'))

        # parse req_mem
        if req_mem[-2] == 'G':
            req_mem_int = int(req_mem[:-2]) * 1000
        elif req_mem[-2] == 'K':
            req_mem_int = int(req_mem[:-2]) / 1000
        else:
            req_mem_int = int(req_mem[:-2])

        mem_eff = (float(maxRSS_list[0])/req_mem_int*int(req_cpus)) * 100
        print('This job used %0.2f%% of its requested memory.' % mem_eff)
        if mem_eff < 20:
            print('Consider requesting less memory to decrease waittime. ')
        print('')
        print('Elapsed Time: %s' % elapsed_list[0])
        print('Requested Time: %s' % req_time)

        time_eff = time_to_int(elapsed_list[0]) / time_to_int(req_time) * 100
        print('This job used %0.2f%% of its requested time.' % time_eff)
        if time_eff < 20:
            print('Consider requesting less time to decrease waittime. ')
    else:
        histogram(maxRSS_list, req_mem=req_mem, req_cpus=req_cpus)
        print('')
        histogram(list(map(time_to_int, elapsed_list)),
                  timeflag=True, req_time=req_time)


if __name__ == '__main__':
        
    parser = argparse.ArgumentParser()
    parser.add_argument('jobid', nargs='?')
    parser.add_argument('-i', '--input', help='input file in current directory')
    args = parser.parse_args()

    arrayID = args.jobID
    inputfile = args.input

    main()
