import argparse
import configparser
import datetime as dt
import os
import subprocess
import shlex
import re
from modules import generate_PBS_script
from modules import process_fastq
from modules import align
from modules.helpers import to_str
from modules import samtools
from modules import counts

##########################################SETUP#########################################


def set_up_file_handles():
    today = dt.datetime.now().strftime("%Y-%m-%d")
    return today


def set_up_logger():
    # todo set up logger/logging

    print("Set up logger!")


def get_second(first):

    pe = re.compile(r'[\W_][0-9][\W_]|[\W_]forward[\W_]')
    matched = pe.search(first).group()
    if "1" in matched:
        new_matched = matched.replace("1", "2")
    else:
        new_matched = matched.replace("forward", "reverse")
    second = first.replace(matched, new_matched)
    return second


def process_config(config_file="config"):  # tested locally

    config = configparser.ConfigParser()
    config.read(config_file)
    config_dict = {}
    for section in config.sections():
        config_dict[section] = {name: value for name, value in config.items(section)}
    return config_dict


def find_files_in_a_tree(folder, file_type='fastq'):

    f_files = []
    for root, dirs, files in os.walk(folder, topdown=False):
        for name in files:
            if name.endswith(file_type):
                f_files.append(os.path.join(root, name))
    return f_files


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


def submit_local_job(script):  # tested locally

    multiple_scripts = script.strip().split("\n")
    out = []
    for scr in multiple_scripts:
        cmd = shlex.split(scr)
        #subprocess.call(cmd)  # blocks until finished
        output = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        output = to_str(output.stdout.read().strip())
        out.append(output)
    return out


def get_args():

    parser = argparse.ArgumentParser("RNASeq Pipeline\n")
    parser.add_argument("-a", "--analysis", help="Analysis options", required=True)
    parser.add_argument("-i", "--input", help="Directory of files", required=True)
    parser.add_argument('-ref', '--reference_genome', help="Reference genome for alignments", required=False)
    parser.add_argument('-gff', '--gff', help="Annotation", required=False)
    parser.add_argument("-local", "--local", help='Run locally or on flux', action='store_true',
                        required=False)
    return parser

###################################SINGLE_FILE_JOBS######################################

def run_trim_job(fastq_file_input, today, config_dict, local=False, job_dependency=''):  # tested locally
    """
    :param fastq_file_input: file name, if PE forward read, assumes reverse
    is in the same location, with same name except 2 instead of one
    :param today: today's date
    :param config_dict: output of process_config
    :param local: whether job is running locally or on flux
    :param job_dependency: if running on flux, whether has to wait for other jobs to finish first
    :return: fastq_file_output path + '' if local, jobid if on flux

    """
    mode = config_dict["sequencing"]["type"]

    assert '.fastq' in fastq_file_input
    out_dir = os.path.dirname(fastq_file_input)
    suffix = to_str(fastq_file_input.split(".fastq")[0])
    if mode == "PE":
        first = os.path.basename(fastq_file_input)
        first_out = os.path.join(out_dir,
                                (to_str(first).split(".fastq")[0] + "_trimmed.fastq"))
        second = os.path.join(out_dir, get_second(first))
        second_out = os.path.join(out_dir,
                                  to_str(second).split(".fastq")[0] + "_trimmed.fastq")
        fastq_file_input = fastq_file_input + " " + second
        fastq_file_output = first_out + " " + second_out
        # todo refactor
    else:
        fastq_file_output = suffix + "_trimmed.fastq"
    script = process_fastq.trimmomatic(fastq_file_input, fastq_file_output, config_dict)
    if local:
        submit_local_job(script)
        return fastq_file_output, ''
    else:
        jobid = submit_flux_job(out_dir, os.path.basename(fastq_file_input).split(".")[0],
                                today, "Trimmomatic", script, job_dependency)
        return fastq_file_output, jobid


def run_fastqc_job(fastq_file, today, config_dict, local=False, job_dependency=''):  # tested locally

    fastqc_bin = config_dict["FastQC"]["bin"]
    file_prefix = os.path.basename(fastq_file).split(".fastq")[0]
    output_directory = os.path.dirname(fastq_file)
    fastqc_output_dir = os.path.join(output_directory, "{}_FastQC_results".format(file_prefix))
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


def run_multiqc_job(fastqc_dir, today, local, job_dependency=''):
    suffix = today + "multiqc_report"
    script = process_fastq.multiqc(fastqc_dir)
    if local:
        submit_local_job(script) # todo: this will not work, do not have multiqc installed
        return fastqc_dir, ""
    else:
        jobid = submit_flux_job(fastqc_dir, suffix, today, "Mqc", script, job_dependency)
        return fastqc_dir, jobid


def run_build_index_job(reference_genome, today, config_dict, local=False, job_dependency=''):  # tested locally
    bowtie_bin = config_dict["Bowtie"]["bin"]
    suffix = to_str(reference_genome.split(".f")[0])
    bt2_base = suffix + '_index'
    script = align.build_bowtie_index(reference_genome, bt2_base, bowtie_bin)
    if local:
        submit_local_job(script)
        return bt2_base, ''
    else:
        output_directory = os.path.dirname(reference_genome)
        suffix = to_str(os.path.basename(reference_genome).split(".f")[0])
        jobid = submit_flux_job(output_directory, suffix,
                                today, "Bowtie_index", script, job_dependency)
        return bt2_base, jobid
    # todo test index job on flux


# 4 Align
def run_alignment_job(fastq_file, bt2_base, config_dict, today, local=False, job_dependency=''):  # tested locally
    output_directory = os.path.dirname(fastq_file)
    bowtie_bin = config_dict["Bowtie"]["bin"]
    mode = config_dict["sequencing"]["type"]
    if mode == "PE":
        first = os.path.basename(fastq_file)
        second = get_second(first)
        fastq_file = "-1 {}  -2 {}".format(fastq_file,
                                           os.path.join(output_directory, second))
    else:
        fastq_file = "-U {}".format(fastq_file)

    suffix = to_str(os.path.basename(fastq_file).split(".")[0])

    sam_file_name = os.path.join(output_directory, suffix + ".sam")
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


def run_sam_to_bam_conversion_and_sorting(sam_file, config_dict, today, local, job_dependency=''):
    # tested locally
    samtools_bin = config_dict["Samtools"]["bin"]
    output_directory = os.path.dirname(sam_file)
    suffix = sam_file.split(".")[0]
    bam_file = suffix+".bam"
    sorted_bam_file = bam_file.split(".bam")[0]+"_sorted.bam"
    script = samtools.sam2bam(sam_file, bam_file, samtools_bin)
    # todo refactor out samtools bin
    if local:
        submit_local_job(script)
        return sorted_bam_file, ''
    else:
        suffix = os.path.basename(sam_file).split(".")[0]
        jobid = submit_flux_job(output_directory, suffix, today, "Sam2Bam", script, job_dependency)
        return sorted_bam_file, jobid


def run_count_job_bedtools(gff, bam, config_dict, today, local, job_dependency=""):
    output_directory = os.path.dirname(bam)
    name = os.path.basename(bam).split(".")[0]
    strand = True if config_dict["bedtools"]["strand"] == "True" else False
    suffix = "st" if strand else "not_st"
    count_file = bam.split(".bam")[0] + "_counts_{}.csv".format(suffix)
    feat = config_dict["bedtools"]["feat"]
    if local:
        count_file = counts.count_with_bedtools_local(gff, bam, count_file, strand, feat)
        return count_file, ''
    else:
        script = counts.count_with_bedtools_flux(gff, bam, count_file, config_dict, strand)
        jobid = submit_flux_job(output_directory, name, today, "Count", script, job_dependency)
        return count_file, jobid

        #
        # with open(count_file, "w") as fo:
        #     for f in counts.features():
        #         if feat not in str(f):
        #             continue
        #         else:
        #             identifier = str(f[-2].split("{}=".format(feat))[1].split(";")[0].strip())
        #             fo.write("{},{}\n".format(identifier, f[-1]))

def run_alignments_for_single_genome(genome, fastq_folder, config_dict, today, local):
    # todo Check if there's an index

    # Build index
    bt2_base, index_jobid = run_build_index_job(genome, today,
                                                config_dict,
                                                local)
    # Get fastq files
    fastq_files = find_files_in_a_tree(fastq_folder, "fastq")
    bams = []
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
        bams.append(bam_file)
    with open(os.path.join(fastq_folder, 'bam_alignment_stats.csv'), "w") as fo:
        fo.write("sample,total,mapped,percent_mapped\n")
        for bam in bams:
            filename = os.path.basename(bam).split(".bam")[0]
            total, mapped, pcnt_mapped = samtools.get_bam_stats(bam)
            fo.write("{},{},{},{}\n".format(filename, total, mapped, pcnt_mapped))


def run_counts_for_single_genome(gff, bam_folder, config_dict, today, local):
    method = config_dict["Counts"]["method"]

    # Get bam files
    bams = find_files_in_a_tree(bam_folder, "bam")
    # todo add bedtools to flux options, right now only local
    if method == 'bedtools':
        for bam in bams:
            count_file, count_jobid = run_count_job_bedtools(gff, bam, config_dict, local, job_dependency="")
    # todo add htseq option
    # todo test this function


"""WORKFLOWS"""


def workflow_test(analysis, input_folder, output_folder):
    return analysis, input_folder, output_folder


def workflow_qc(fastq_dir, config_dict, today, local=False):
    files = find_files_in_a_tree(fastq_dir, file_type='fastq')
    for file in files:
        run_fastqc_job(file, today, config_dict, local)
    return "Fastqc jobs submitted!"


def workflow_mqc(fastqc_dir, today, local):
    run_multiqc_job(fastqc_dir, today, local)
    return "Multiqc jobs submitted!"


def workflow_trim_and_qc(fastq_dir, config_dict, today, local=False):

    files = find_files_in_a_tree(fastq_dir, file_type='fastq')
    for file in files:
        # Run trim job
        trimmed_fastq_file, trim_jobid = run_trim_job(file, today, config_dict, local)
        # Run fastqc job
        run_fastqc_job(trimmed_fastq_file, today, config_dict, local, trim_jobid)
    return "Jobs for trim and qc submitted"  # todo test workflow1 on flux


def workflow_align(fastq_dir, ref, config_dict, today, local):

    if local:
        # 1. Build index
        print("Building index...")
        bt2, _ = run_build_index_job(ref, today, config_dict, local)
        print("Index complete, index name: {}".format(bt2))
        # 2. Find fastq files
        print("Looking for fastq files")
        fastq_files = find_files_in_a_tree(fastq_dir, file_type='fastq')
        print("Found {} fastq files".format(len(fastq_files)))
        # 3. Iterate over them and align
        for file in fastq_files:
            print("Aligning {}".format(file))
            sam_file, _ = run_alignment_job(file, bt2, config_dict, today, local)
            print("Sorting {}".format(sam_file))
            sorted_bam, _ = run_sam_to_bam_conversion_and_sorting(sam_file, config_dict, today, local)
            print("Counting {}".format(sorted_bam))
            #counts_file, _ = run_count_job_bedtools(gff, sorted_bam, config_dict, today, local)
            #print("Counting complete, count file: {}".format(counts_file))

    else:
        job_ids = {}
        # 1. Build index
        bt2, index_jobid = run_build_index_job(ref, today, config_dict, local)
        # 2. Find fastq files
        fastq_files = find_files_in_a_tree(fastq_dir, file_type='fastq')
        mode = config_dict["sequencing"]["type"]
        # 3. Iterate over them and align
        for file in fastq_files:
            if mode == "PE":
                first = os.path.basename(file)
                second = get_second(first)
                if first == second:
                    continue
            sam_file, samfile_jobid = run_alignment_job(file, bt2, config_dict,
                                                        today, local, index_jobid)
            sorted_bam, sam2bam_jobid = run_sam_to_bam_conversion_and_sorting(sam_file,
                                                                              config_dict,
                                                                              today, local,
                                                                              samfile_jobid)
            # counts_file, counts_jobid = run_count_job_bedtools(gff, sorted_bam,
            #                                                    config_dict, today,
            #                                                    local, sam2bam_jobid )
            job_ids[file] = [samfile_jobid, sam2bam_jobid,]# counts_jobid]
        return job_ids


# def workflow_align(genome, fastq_folder, config_dict, today, local):
#
#     run_alignments_for_single_genome(genome, fastq_folder, config_dict, today, local)
#     return "Simple Align Workflow!"


def workflow_count(gff, bam_folder, config_dict, today, local):
    bams = find_files_in_a_tree(bam_folder, file_type="bam")
    for bam in bams:
        run_count_job_bedtools(gff, bam, config_dict, today, local)



####################################################################################################


# NEED TO ADD local option to these



#
# def run_count_job_htseq(gff, bam, config_dict, local, job_dependency=""):
#


#
# def run_alignments_for_multiple_genomes(genome_read_pairs, today, config_dict): #list of tuples
#     bowtie_bin = config_dict["Bowtie"]["bin"]
#     samtools_bin = config_dict["Samtools"]["bin"]
#     for genome_read_pair in genome_read_pairs:
#         genome = genome_read_pair[0]
#         fastq_file = genome_read_pair[1]
#         output_directory = genome_read_pair[2]
#         #run build index
#         bt2_base, index_jobid = run_build_index_job(genome, output_directory,
#                             today, bowtie_bin)
#         #run alignment job
#         sam_file, align_jobid = run_alignment_job(fastq_file, output_directory,
#                           bt2_base, bowtie_bin, today,
#                           job_dependency=index_jobid)
#         #run sam job
#         # bam_file, samtools_jobid = run_sam_to_bam_conversion_and_sorting(sam_file,
#         #                                                                  output_directory,
#         #                                                                  today,
#         #                                                                  samtools_bin,
#         #                                                                  job_dependency=align_jobid)


def flow_control():

    today = set_up_file_handles()
    args = get_args().parse_args()

    if args.local:
        config_dict = process_config("local_config")
    else:
        config_dict = process_config("config")

    if args.analysis == 'test':
        print(workflow_test(args.analysis, args.input, args.out_dir))
    elif args.analysis == 'qc':
        print(workflow_qc(args.input, config_dict, today, args.local))
    elif args.analysis == 'mqc':
        print(workflow_mqc(args.input, today, args.local))
    elif args.analysis == 'trim':
        print(workflow_trim_and_qc(args.input, config_dict, today, args.local))
    elif args.analysis == 'align':  # tested locally
        print(workflow_align(args.input, args.reference_genome, config_dict, today, args.local))

    elif args.analysis == 'count':  #todo test
        assert args.gff
        workflow_count(args.gff, args.input, config_dict, today, args.local)


if __name__ == "__main__":
    flow_control()

