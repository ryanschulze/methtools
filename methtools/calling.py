#!/usr/bin/env python
# -*- coding: UTF-8 -*-

import os, sys
import argparse
import pysam
from collections import defaultdict
import numpy as np
import multiprocessing
import tempfile
import shutil

"""
    The standard output is BED6 format, unless the option --methylkit is given.
    In that case the output will be in the methylkit format like the example below.

    Example Mythylkit methcall file:

    chrBase	chr	base	strand	coverage	freqC	freqT
    chr7.3295868	chr7	3295868	R	14	85.71	14.29

"""

def process_call_string( letter, key, CGmethHash, nonCGmethHash,  CHHmethHash,  CHGmethHash, unknown_methHash ):

    if letter.upper() == "Z":
        # if genomic base is CpG
        if not CGmethHash.has_key(key):
            CGmethHash[ key ] = [ 0, 0, 0 ]

        if letter == "Z":
            # update Cs
            CGmethHash[key][0] += 1
        elif letter == "z":
            # update Ts
            CGmethHash[key][1] += 1
        else:
            # update other bases
            CGmethHash[key][2] += 1
    elif letter in ["U","u"]:
        # if methylated C is in an unknown context
        if not unknown_methHash.has_key(key):
            unknown_methHash[ key ] = [ 0, 0, 0 ]

        if letter == "Z":
            # update Cs
            unknown_methHash[key][0] += 1
        elif letter == "z":
            # update Ts
            unknown_methHash[key][1] += 1
        else:
            # update other bases
            unknown_methHash[key][2] += 1
    elif letter in ["X","x"]:
        # methylated C in CHG context or unmethylated C in CHG context
        if not CHGmethHash.has_key(key):
            CHGmethHash[ key ] = [ 0, 0, 0 ]

        if letter == "Z":
            # update Cs
            CHGmethHash[key][0] += 1
        elif letter == "z":
            # update Ts
            CHGmethHash[key][1] += 1
        else:
            # update other bases
            CHGmethHash[key][2] += 1
    elif letter in ["H","h"]:
        # methylated C in CHH context or unmethylated C in CHH context
        if not CHHmethHash.has_key(key):
            CHHmethHash[ key ] = [ 0, 0, 0 ]

        if letter == "Z":
            # update Cs
            v[key][0] += 1
        elif letter == "z":
            # update Ts
            CHHmethHash[key][1] += 1
        else:
            # update other bases
            CHHmethHash[key][2] += 1
    else:
        sys.exit('Error: Unknown methylation encoding found.')

    return (CGmethHash, nonCGmethHash,  CHHmethHash,  CHGmethHash, unknown_methHash)


# process a given CG methlation hash
# writes the filter passing CGs to output file
def processCGmethHash( CGmethHash, out, options ):
    min_cov = options.min_cov
    for key in CGmethHash.keys():
        strand, chr, loc = key.split('|')
        noCs,noTs,noOs = CGmethHash[key]
        temp_sum = (noTs + noCs + noOs)
        Cperc = "%.2f" % ( 100.0 * noCs / temp_sum )
        Tperc = "%.2f" % ( 100.0 * noTs / temp_sum )
        if float( noTs + noCs ) / temp_sum > 0.9 and temp_sum >= min_cov:
            if options.is_methylkit:
                out.write( "\t".join( ["%s.%s" % (chr,loc), chr, loc, strand, str(temp_sum), Cperc, Tperc] ) + "\n")
            else:
                if strand == 'F':
                    strand = '+'
                elif strand == 'R':
                    strand = '-'
                out.write( "\t".join( [chr, str(int(loc)-1), loc, "%s" % temp_sum, Cperc, strand] ) + "\n")
    CGmethHash = {}

def processCHmethHash( CGmethHash, out, options ):
    min_cov = options.min_cov
    for key in CGmethHash.keys():
        strand, chr, loc = key.split('|')
        noCs,noTs,noOs = CGmethHash[key]
        temp_sum = (noTs + noCs + noOs)
        Cperc = "%.2f" % ( 100.0 * noCs / temp_sum )
        Tperc = "%.2f" % ( 100.0 * noTs / temp_sum )
        if float( noTs + noCs ) / temp_sum > 0.9 and temp_sum >= min_cov:
            if options.is_methylkit:
                out.write( "\t".join( ["%s.%s" % (chr,loc), chr, loc, strand, str( temp_sum ), Cperc, Tperc] ) + "\n")
            else:
                if strand == 'F':
                    strand = '+'
                elif strand == 'R':
                    strand = '-'
                out.write( "\t".join( [chr, str(int(loc)-1), loc, "%s" % temp_sum, Cperc, strand] ) + "\n")
    CGmethHash = {}

# process a given non CG methlation hash
# writes the filter passing Cs to a hash, that hash will be used to calculate conversion rate later on
"""
def processnonCGmethHash( nonCGmethHash, summary_forward_temp, summary_reverse_temp, options ):
    min_cov = options.min_cov
    for key in nonCGmethHash.keys():
        strand, chr, loc = key.split('|')
        noCs,noTs,noOs = nonCGmethHash[key]
        temp_sum = noTs + noCs + noOs
        Cperc = "%.2f" % (100.0 * noCs / temp_sum )
        Tperc = "%.2f" % (100.0 * noTs / temp_sum )
        if float( noTs + noCs ) / temp_sum > 0.95 and temp_sum >= min_cov:
            if strand == 'F':
                summary_forward_temp.write( "%s\n" % ((noTs * 100.0) / temp_sum) )
            else:
                summary_reverse_temp.write( "%s\n" % ((noTs * 100.0) / temp_sum) )
    nonCGmethHash = {}
"""


def process_cigar(cigar, mcalls, quals):
    """
    Processes the cigar string and remove and delete elements from mcalls and quality scores
    Cigar is a tuple of tuples (operation, length). Operation can be one of the following:
    MATCH = 0
    INS = 1
    DEL = 2
    REF_SKIP = 3
    SOFT_CLIP = 4
    HARD_CLIP = 5
    PAD = 6

    >>> process_cigar(((0,18),(1,5),(0,12)), '...hh..x......h....h.h......h.z....', '<<<<<<<<<<<<<:<<<<<<<<<<<<<<<<<<<<<' )
    ('...hh..x......h........h.z....', '<<<<<<<<<<<<<:<<<<<<<<<<<<<<<<')

    """
    new_quals = ''
    new_mcalls = ''
    current_position = 0
    for operation, length in cigar:
        if operation == 0: # match
            new_quals += quals[current_position:current_position+length]
            new_mcalls += mcalls[current_position:current_position+length]
        elif operation == 1: # insertions
            pass
        elif operation == 2: # deletions
            new_quals += '.' * length
            new_mcalls += '.' * length
        current_position += length
    return (new_mcalls,new_quals)


def process_sam(options, chromosome, temp_dir):
    min_qual = options.min_qual
    # create temp files
    if options.CpG:
        out_temp = tempfile.NamedTemporaryFile(dir=temp_dir, prefix='CpG', delete=False)
    if options.CHH:
        CHH_out_temp = tempfile.NamedTemporaryFile(dir=temp_dir, prefix='CHH', delete=False)
    if options.CHG:
        CHG_out_temp = tempfile.NamedTemporaryFile(dir=temp_dir, prefix='CHG', delete=False)
    if options.unknown:
        unknown_out_temp = tempfile.NamedTemporaryFile(dir=temp_dir, prefix='unknown', delete=False)


    """
    if options.summary:
        summary_reverse_temp =  tempfile.NamedTemporaryFile(dir=temp_dir, prefix='nonCpG_reverse', delete=False)
        summary_forward_temp =  tempfile.NamedTemporaryFile(dir=temp_dir, prefix='nonCpG_forward', delete=False)
    """

    samfile = pysam.Samfile( options.input_path, 'rb' )
    offset = 33
    if options.phred64:
        offset = 64

    nonCGmethHash = dict()
    CGmethHash = dict()
    CHHmethHash = dict()
    CHGmethHash = dict()
    unknown_methHash = dict()

    start_pre = -1
    chr_pre = ''
    last_pos  =-1
    last_chrom = None

    try:
        samfile_iterator = samfile.fetch(chromosome)
    except:
        sys.stderr.write('Could not fetch chromosome from BAM file. Probably the index is missing or currupted.\n')
        return (CGmethHash, CHHmethHash, CHGmethHash, unknown_methHash)
    # for every read in the sam file
    for iteration, read in enumerate(samfile_iterator):
        start = read.pos + 1 # 0 based leftmost coordinate
        end = read.aend     # aligned end position of the read -> read.rlen + start + 1 # or len(read.seq)+start+1
        chr = samfile.getrname( read.tid )
        methc = read.opt('XM')
        mcalls = methc      # methylation calls
        quals = read.qual   # quality scores
        mrnm = read.mrnm    # the reference id of the mate
        mpos = read.mpos + 1    # the position of the mate
        isize = read.isize  #read.tlen
        slen = read.rlen    # alignment sequence length
        cigar = read.cigar  # cigar string
        mcalls, quals = process_cigar(cigar, mcalls, quals)
        #process_cigar(((0,18),(1,5),(0,12)), '...hh..x......h....h.h......h.z....', '<<<<<<<<<<<<<:<<<<<<<<<<<<<<<<<<<<<' )

        # get strand
        if read.opt('XR') == 'CT' and read.opt('XG') == 'CT':
            # original top strand
            strand = '+'
        elif read.opt('XR') == 'CT' and read.opt('XG') == 'GA':
            # original bottom strand
            strand = '-'
        elif read.opt('XR') == 'GA' and read.opt('XG') == 'CT':
            # complementary to original top strand, bismark says - strand to this
            strand = '+'
        elif read.opt('XR') == 'GA' and read.opt('XG') == 'GA':
            # complementary to original bottom strand, bismark says + strand to this
            strand = '-'
        else:
            sys.stdout.write('Warning: No strand found for %s (chr) %s (start) %s (end). Skip read.' % (chr, start, end))
            continue
        # Check if the file is sorted
        if chr == chr_pre:
            if start_pre > start:
                sys.exit("The sam file is not sorted properly you can sort the file in unix-like machines using:\n grep -v '^[[:space:]]*\@' test.sam | sort -k3,3 -k4,4n  > test.sorted.sam \n")
        chr_pre = chr
        start_pre = start

        """
            if there is no_overlap, trim the mcalls and quals
            adjust the start
        """

        if options.no_overlap and mrnm == '=' and options.paired:
            if (start + slen -1) > mpos:
                if (mpos - start):
                    mcalls = mcalls[: mpos-start]
                    quals = quals[: mpos-start]

        """
        if($nolap && ( ($mrnm eq "=") && $paired ) ){

            if( ($start+$slen-1)>$mpos){
                if(($mpos-$start)>0)
                    { 
                splice @mcalls,($mpos-$start);
                splice @quals,($mpos-$start);
            }
          }
        }
        """

        # we can write the results as soon as we processing a new chromosome
        # or a sequence/read with a distance larger than the read length away from the last processed sequence/read
        # Therewith we garantee that we are counting the coverage in a correct way -> given that the SAM/BAM file is sorted
        if (start - last_pos > options.readlen and last_pos != -1) or (chr != last_chrom and last_chrom != None):
            #processnonCGmethHash( nonCGmethHash, summary_forward_temp, summary_reverse_temp, options )
            #nonCGmethHash = dict()
            if options.CpG:
                processCGmethHash( CGmethHash, out_temp, options )
            if options.CHH:
                processCHmethHash( CHHmethHash, CHH_out_temp, options)
            if options.CHG:
                processCHmethHash( CHGmethHash, CHG_out_temp, options)
            if options.unknown:
                processCHmethHash( unknown_methHash, unknown_out_temp, options)
            CGmethHash = dict()
            CHHmethHash = dict()
            CHGmethHash = dict()
            unknown_methHash = dict()


        for index, letter in enumerate(quals):
            if ord(letter) - offset < min_qual or mcalls[index] == '.':
                continue
            if strand == '+':
                key = '|'.join( ["F",chr,str(start + index)] )
            else:
                key = '|'.join( ["R",chr,str(start + index)] )

            process_call_string(mcalls[index], key, CGmethHash, nonCGmethHash, CHHmethHash, CHGmethHash, unknown_methHash)

        last_pos = end
        last_chrom = chr

    samfile.close()
    #if options.summary:
    #    processnonCGmethHash( nonCGmethHash, summary_forward_temp, summary_reverse_temp, options )
    #    nonCGmethHash = dict()
    #    summary_forward_temp.close()
    #    summary_reverse_temp.close()

    if options.CpG:
        processCGmethHash( CGmethHash, out_temp, options )
    if options.CHH:
        processCHmethHash( CHHmethHash, CHH_out_temp, options)
    if options.CHG:
        processCHmethHash( CHGmethHash, CHG_out_temp, options)
    if options.unknown:
        processCHmethHash( unknown_methHash, unknown_out_temp, options)

    # close temp files
    if options.CpG:
        out_temp.close()
    if options.CHH:
        CHH_out_temp.close()
    if options.CHG:
        CHG_out_temp.close()
    if options.unknown:
        unknown_out_temp.close()

    return (CGmethHash, CHHmethHash, CHGmethHash, unknown_methHash)



def run_calc( args ):
    """
        Multiprocessing helper function.
        Getting Jobs out of the in_queue, calculate the percentage for that chromosome and returns the results.
    """
    temp_dir, options, chromosome = args
    return process_sam( options, chromosome, temp_dir )


def calling( options ):
    """

    """
    out = None
    CHH_out = None
    CHG_out = None
    unknown_out = None
    min_cov = options.min_cov

    if options.CpG:
        out = open( options.CpG, 'wb+')
        if options.is_header:
            if options.is_methylkit:
                out.write( "chrBase\tchr\tbase\tstrand\tcoverage\tfreqC\tfreqT\n" )
            else:
                out.write( "chr\tstart\tend\tname\tscore\tstrand\n" )

    if options.CHH:
        CHH_out = open( options.CHH, 'wb+' )
        if options.is_header:
            if options.is_methylkit:
                CHH_out.write( "chrBase\tchr\tbase\tstrand\tcoverage\tfreqC\tfreqT\n" )
            else:
                CHH_out.write( "chr\tstart\tend\tname\tscore\tstrand\n" )

    if options.CHG:
        CHG_out =  open( options.CHG, 'wb+' )
        if options.is_header:
            if options.is_methylkit:
                CHG_out.write( "chrBase\tchr\tbase\tstrand\tcoverage\tfreqC\tfreqT\n" )
            else:
                CHG_out.write( "chr\tstart\tend\tname\tscore\tstrand\n" )

    if options.unknown:
        unknown_out =  open( options.unknown, 'wb+' )
        if options.is_header:
            if options.is_methylkit:
                unknown_out.write( "chrBase\tchr\tbase\tstrand\tcoverage\tfreqC\tfreqT\n" )
            else:
                unknown_out.write( "chr\tstart\tend\tname\tscore\tstrand\n" )


    print("Multiprocessing mode started with %s" % options.processors)

    # creating temp dir and and store all temporary results there
    temp_dir = tempfile.mkdtemp()
    tmpbam = tempfile.NamedTemporaryFile( dir=temp_dir )
    tmpbam_path = tmpbam.name
    tmpbam.close()
    #link bam and bam index to working directory, the *.bai index need to live besides the bam file
    new_bam_path = '%s.bam' % tmpbam_path
    os.symlink( options.input_path, new_bam_path )
    os.symlink( options.bam_index, '%s.bam.bai' % tmpbam_path )
    options.input_path = new_bam_path
    samfile = pysam.Samfile( options.input_path, 'rb' )
    # building a triple for each multiprocessing run -> (temp_dir, options, one chromosome)
    refs = samfile.references
    references = zip([temp_dir]*len( refs ), [options]*len( refs ), refs)
    samfile.close()

    results_iterator = []
    p = multiprocessing.Pool( options.processors )
    p.map_async(run_calc, references, callback=results_iterator.extend)
    #for reference in references:
    #    results_iterator.extend( run_calc(reference) )
    p.close()
    p.join()
    #if options.summary:
    #    temp_summary_forward = tempfile.NamedTemporaryFile(dir=temp_dir, delete=False)
    #    temp_summary_reverse = tempfile.NamedTemporaryFile(dir=temp_dir, delete=False)

    if options.CpG:
        for filename in os.listdir(temp_dir):
            if filename.startswith('CpG'):
                shutil.copyfileobj( open(os.path.join(temp_dir, filename), "rb"), out )
        out.close()
    if options.CHH:
        for filename in os.listdir(temp_dir):
            if filename.startswith('CHH'):
                shutil.copyfileobj( open(os.path.join(temp_dir, filename), "rb"), CHH_out )
        CHH_out.close()
    if options.CHG:
        for filename in os.listdir(temp_dir):
            if filename.startswith('CHG'):
                shutil.copyfileobj( open(os.path.join(temp_dir, filename), "rb"), CHG_out )
        CHG_out.close()
    if options.unknown:
        for filename in os.listdir(temp_dir):
            if filename.startswith('unknown'):
                shutil.copyfileobj( open(os.path.join(temp_dir, filename), "rb"), unknown_out )
        unknown_out.close()

    """
    if options.summary:
        for filename in os.listdir(temp_dir):
            if filename.startswith('nonCpG_forward'):
                shutil.copyfileobj( open(os.path.join(temp_dir, filename)), temp_summary_forward )
            if filename.startswith('nonCpG_reverse'):
                shutil.copyfileobj( open(os.path.join(temp_dir, filename)), temp_summary_reverse )
        temp_summary_forward.close()
        temp_summary_reverse.close()
        summary_forward = np.loadtxt( temp_summary_forward.name )
        summary_reverse = np.loadtxt( temp_summary_reverse.name )
    """
    # cleaning temporary working directory
    shutil.rmtree( temp_dir )

    """
    if not options.summary:
        return

    for arg, value in sorted(vars(options).items()):
        options.summary.write("Argument %s: %r", arg, value)

    options.summary.write('\n\n')

    # get the conversion rate and write it out!!
    numF = len( summary_forward )#len( pMeth_nonCG.get( "F", []) )
    numR = len( summary_reverse )#len( pMeth_nonCG.get( "R", []) )

    if numF == 0 and numR == 0:
        sys.exit("\nnot enough alignments that pass coverage and phred score thresholds to calculate conversion rates\n EXITING....\n")

    both_strands = np.concatenate( (summary_forward, summary_reverse) )#pMeth_nonCG.get( "F", []) + pMeth_nonCG.get( "R", [])

    medFconvRate = 0
    medRconvRate = 0
    AvFconvRate = sum( summary_forward ) / numF
    AvRconvRate = sum( summary_reverse ) / numR
    AvconvRate = sum( both_strands ) / (numF + numR)


    if numF > 0:
        medFconvRate = np.median( summary_forward )

    if numR > 0:
        medRconvRate = np.median( summary_reverse )

    medconvRate = np.median( both_strands )

    totCpG = len( both_strands )

    res = "total otherC considered (>95%% C+T): %s\n" % totCpG
    res += "average conversion rate = %s\n" % AvconvRate
    res += "median conversion rate = %s\n\n" % medconvRate 

    res += "total otherC considered (Forward) (>95%% C+T): %s\n" % numF
    res += "average conversion rate (Forward) = %s\n" % AvFconvRate
    res += "median conversion rate (Forward) = %s\n\n" % medFconvRate

    res += "total otherC considered (Reverse) (>95%% C+T): %s\n" % numR
    res += "average conversion rate (Reverse) = %s\n" % AvRconvRate
    res += "median conversion rate (Reverse) = %s\n" % medRconvRate
    options.summary.write('res')
    """

def main():
    parser = argparse.ArgumentParser(description='Base methylation calling from Bismark SAM files.')

    parser.add_argument("-i", "--input", dest="input_path",
                    required=True,
                    help="Path to the BAM input file.")

    parser.add_argument("--bam-index", dest="bam_index",
                    help="Path to the bam index.")

    parser.add_argument("--CpG", dest="CpG",
                    help="output filename for CpG methylation scores (if not specified no file is written out)")

    parser.add_argument("--CHH", dest="CHH",
                    help="output filename for CHH methylation scores (if not specified no file is written out)")

    parser.add_argument("--CHG", dest="CHG",
                    help="output filename for CHG methylation scores (if not specified no file is written out)")

    parser.add_argument("--unknown", dest="unknown",
                    help="output filename for methylation sites with unknown context (if not specified no file is written out)")

    parser.add_argument("--phred64", dest="phred64", action="store_true", default=False,
                    help="quality scores phred64 scale used otherwise phred33 is the default")

    parser.add_argument("--mincov", dest="min_cov", default=0, type=int,
                    help="min coverage (default:0)")

    parser.add_argument("--minqual", dest="min_qual", default=20, type=int,
                    help="minquality (default:20)")

    parser.add_argument("--methylkit", dest="is_methylkit", action="store_true", default=False,
                    help="Output will be in methylkit format. Default output format is BED6 format.")

    parser.add_argument("--paired", dest="paired", action="store_true", default=False,
                    help="Paired end SAM/BAM file.")

    parser.add_argument("--header", dest="is_header", action="store_true", default=False,
                    help="Print header into the output file.")

    parser.add_argument("--readlen", default=100, type=int,
                    help="Read length (default:100)")

    parser.add_argument("--no-overlap", dest="no_overlap", action="store_true", default=False,
                    help="Overlap allowed? TODO")

    #parser.add_argument("--summary",
    #                help="Create a summary file, this can take a significant amount of time and memory.")

    parser.add_argument('-p', '--processors', type=int, 
        default=multiprocessing.cpu_count())

    options = parser.parse_args()

    calling(options)

if __name__ == '__main__':
    import doctest
    doctest.testmod()
    main()
