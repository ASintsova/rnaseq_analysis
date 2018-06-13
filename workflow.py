import argparse
import configparser
import datetime as dt
import os
import subprocess
import shlex

from modules import generate_PBS_script
from modules import process_fastq
from modules import align
from modules.helpers import to_str
from modules import samtools


def set_up_file_handles():
    today = dt.datetime.now().strftime("%Y-%m-%d")
    return today


def set_up_logger():
    # todo set up logger/logging

    print("Set up logger!")


def process_config(config_file="config"):

    config = configparser.ConfigParser()
    config.read(config_file)
    config_dict = {}
    for section in config.sections():
        config_dict[section] = {name: value for name, value in config.items(section)}
    return config_dict


def submit_flux_job(output_directory, suffix, today, job_name, script, job_dependency=''):

    pbs_name = os.path.join(output_directory, today+"_{}_{}.pbs".format(suffix, job_name))
    generate_PBS_script.generate_PBS_script(pbs_name, script)
    if job_dependency:
        output = subprocess.Popen(["qsub", "-W",
                                  "depend=afterok:{}".format(job_dependency),
                                   pbs_name], stdout=subprocess.PIPE)
    else:
        output = subprocess.Popen(["qsub", pbs_name], stdout=subprocess.PIPE)
    output = output.stdout.read().split(".")[0]
    return to_str(output)


def submit_local_job(script):

    multiple_scripts = script.strip().split("\n")
    for scr in multiple_scripts:
        cmd = shlex.split(scr)
        subprocess.call(cmd)  # blocks until finished


def get_args():

    parser = argparse.ArgumentParser("RNASeq Pipeline\n")
    parser.add_argument("-a", "--analysis", help="Analysis options", required=True)
    parser.add_argument("-i", "--input", nargs='+', help="List of files", required=True)
    parser.add_argument("-o", "--out_dir", help="Location of the output directory", required=False)
    parser.add_argument('-ref', '--reference_genome', help="Reference genome for alignments", required=False)
    parser.add_argument('--no_index', help="Don't build bowtie2 index again", action="store_true",
                        required=False)  # explore metavar
    parser.add_argument("-local", "--local", help='Run locally or on flux', action='store_true',
                        required=False)

    return parser

#######################################################################################################


"""

worklfow 1: testing

input: fastq file, output directory
output: trimmed fastq file, fastqc output

step 1. run trimmomatic
step 2. run fastqc on trimmed fastq file


"""


def run_trim_job(fastq_file_input, output_directory, today,
                 config_dict, local=False,
                 job_dependency=''):
    """

    :param fastq_file_input: single fastq file (can be gzipped)
    :param output_directory: output directory
    :param today: today's date
    :param config_dict: output of process_config
    :param local: whether job is running locally or on flux
    :param job_dependency: if running on flux, whether has to wait for other jobs to finish first
    :return: fastq_file_output path + '' if local, jobid if on flux

    """

    assert '.fastq' in fastq_file_input
    assert os.path.isdir(output_directory)

    trimmomatic_bin = config_dict["Trimmomatic"]["bin"]
    trimmomatic_adapters = config_dict["Trimmomatic"]["adapters"]

    suffix = to_str(os.path.basename(fastq_file_input).split(".fastq")[0])

    fastq_file_output = os.path.join(output_directory, suffix+"_trimmed.fastq")
    script = process_fastq.trimmomatic(fastq_file_input,
                                       fastq_file_output,
                                       trimmomatic_bin,
                                       trimmomatic_adapters)
    if local:
        print(script)
        submit_local_job(script)
        return fastq_file_output, ''
    else:
        jobid = submit_flux_job(output_directory, suffix,
                                today, "Trimmomatic", script, job_dependency)
        return fastq_file_output, jobid


def run_fastqc_job(fastq_file, output_directory, today,
                   config_dict, local=False, job_dependency=''):

    fastqc_bin = config_dict["FastQC"]["bin"]
    fastqc_output_dir = os.path.join(output_directory, "FastQC_results")
    subprocess.call(["mkdir", "-p", fastqc_output_dir])
    script = process_fastq.fastqc(fastq_file, fastqc_output_dir,
                                  fastqc_bin)

    suffix = os.path.basename(fastq_file).split(".")[0]
    if local:
        submit_local_job(script)
        return fastqc_output_dir, ''
    else:
        jobid = submit_flux_job(output_directory, suffix,
                                today, "FastQC", script, job_dependency)
        return fastqc_output_dir, jobid


def workflow1(files, output_directory, config_dict, today, local=False):

    for file in files:

        suffix = to_str(os.path.basename(file).split(".")[0]) + "_output"
        out_dir = os.path.join(output_directory, suffix)
        subprocess.call(["mkdir", "-p", out_dir])

        # 2. run trim job
        trimmed_fastq_file, trim_jobid = run_trim_job(file, out_dir, today,
                                                      config_dict, local)

        fastqc_output_dir, fastqc_jobid = run_fastqc_job(trimmed_fastq_file,
                                                         out_dir, today,
                                                         config_dict, local,
                                                         job_dependency=trim_jobid)
    return "Jobs for workflow1 submitted" # todo test workflow1 on flux



####################################################################################################


"""
workflow2:

take reference file, build index
take a list of fastq files align with bowtie

if both are directories have to have a function that matches jobs/files 

"""

# NEED TO ADD local option to these


def run_build_index_job(reference_genome,
                        today, config_dict,
                        local=False, job_dependency=''):
    bowtie_bin = config_dict["Bowtie"]["bin"]
    suffix = to_str(reference_genome.split(".f")[0])
    bt2_base = suffix + '_index'
    script = align.build_bowtie_index(reference_genome,
                                      bt2_base,
                                      bowtie_bin)
    print(script)
    if local:
        submit_local_job(script)
        return bt2_base, ''
    else:
        output_directory = os.path.dirname(reference_genome)
        jobid = submit_flux_job(output_directory, suffix,
                                today, "Bowtie_index", script, job_dependency)
        return bt2_base, jobid
     # todo test index job on flux


def run_alignment_job(fastq_file,
                      # output directory is fastqfile directory
                      bt2_base, config_dict, today,
                      local=False,
                      job_dependency=''):
    output_directory = os.path.dirname(fastq_file)
    bowtie_bin = config_dict["Bowtie"]["bin"]
    suffix = to_str(os.path.basename(fastq_file).split(".")[0])
    sam_file_name = os.path.join(output_directory, suffix  + ".sam")
    script = align.bowtie_align(fastq_file,
                                sam_file_name,
                                bt2_base,  bowtie_bin)
    if local:
        submit_local_job(script)
        return sam_file_name, ''
    else:
        jobid = submit_flux_job(output_directory, suffix,
                                today, "Bowtie_Align", script, job_dependency)
        return sam_file_name, jobid
    # todo test on flux


def run_sam_to_bam_conversion_and_sorting(sam_file, config_dict, today,
                                          local, job_dependency=''):
    samtools_bin = config_dict["Samtools"]["bin"]
    output_directory = os.path.dirname(sam_file)
    suffix = sam_file.split(".")[0]
    bam_file = suffix+".bam"
    flagstat_file = suffix+"_flagstat.txt"

    script = samtools.sam2bam(sam_file, bam_file,
                              flagstat_file,
                              samtools_bin)
    if local:
        submit_local_job(script) # todo make flagstat work for local run
        return bam_file, ''
    else:
        jobid = submit_flux_job(output_directory, suffix, # todo make sure suffix/output_directory still work
                                today, "Bowtie_Align", script, job_dependency)
        return bam_file, jobid


def run_alignments_for_multiple_genomes(genome_read_pairs, today, config_dict): #list of tuples
    bowtie_bin = config_dict["Bowtie"]["bin"]
    samtools_bin = config_dict["Samtools"]["bin"]
    for genome_read_pair in genome_read_pairs:
        genome = genome_read_pair[0]
        fastq_file = genome_read_pair[1]
        output_directory = genome_read_pair[2]
        #run build index
        bt2_base, index_jobid = run_build_index_job(genome, output_directory,
                            today, bowtie_bin)
        #run alignment job
        sam_file, align_jobid = run_alignment_job(fastq_file, output_directory,
                          bt2_base, bowtie_bin, today,
                          job_dependency=index_jobid)
        #run sam job
        # bam_file, samtools_jobid = run_sam_to_bam_conversion_and_sorting(sam_file,
        #                                                                  output_directory,
        #                                                                  today,
        #                                                                  samtools_bin,
        #                                                                  job_dependency=align_jobid)

def find_fastq_files_in_a_tree(folder, file_type): # todo refactor function name

    fastq_files = []
    for root, dirs, files in os.walk(folder, topdown=False):
        for name in files:
            if file_type in name:
                fastq_files.append(os.path.join(root, name))
    return fastq_files


def run_alignments_for_single_genome(genome, fastq_folder, config_dict, today, local):
    # todo Check if there's an index

    # Build index
    bt2_base, index_jobid = run_build_index_job(genome, today,
                                                config_dict,
                                                local)
    # Get fastq files
    fastq_files = find_fastq_files_in_a_tree(fastq_folder, "fastq")

    # run alignment job
    for fastq_file in fastq_files:

        sam_file, align_jobid = run_alignment_job(fastq_file,
                                                  bt2_base, config_dict,
                                                  today, local,
                                                  job_dependency=index_jobid)
    # run sam job
        bam_file, samtools_jobid = run_sam_to_bam_conversion_and_sorting(sam_file,
                                                                         config_dict,
                                                                         today,
                                                                         local,
                                                                         align_jobid)



def workflow2():
    return "Second Workflow!"


def workflow_test(analysis, input_folder, output_folder):
    return analysis, input_folder, output_folder


#####################################################################################################
"""
WORKFLOW3:

take annotation, sorted bam files plot saturation curves, 
and count reads, combine reads into single files, calculate RPKMs

"""

#####################################################################################################


def flow_control():

    today = set_up_file_handles()
    args = get_args().parse_args()
    if os.path.isdir(args.input[0]):
        files = [os.path.join(os.path.abspath(args.input[0]), fi) for fi in os.listdir(args.input[0])]
    elif args.input:
        files = [os.path.abspath(fi) for fi in args.input]
    else:
        raise IOError
    output_directory = os.path.abspath(args.out_dir)
    subprocess.call(["mkdir", "-p", output_directory])
    if args.local:
        config_dict = process_config("local_config")
    else:
        config_dict = process_config("config")

    if args.analysis == 'test':
        print(workflow_test(args.analysis, args.input, args.out_dir))

    elif args.analysis == 'workflow1':
        print(workflow1(files, output_directory, config_dict, today, args.local))


if __name__ == "__main__":
    sam_file = "/Users/annasintsova/git_repos/code/data/reads/SRR1051511_trimmed.sam"
    config_dict = process_config(config_file="local_config")
    today = set_up_file_handles()
    local = True
    run_sam_to_bam_conversion_and_sorting(sam_file, config_dict,
                                          local, job_dependency='')