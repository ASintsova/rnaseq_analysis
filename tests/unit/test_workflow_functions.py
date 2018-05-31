import datetime as dt
import os
import pytest
import subprocess
import sys
sys.path.append('.')
import workflow
from modules.helpers import to_str


#today = dt.datetime.today().strftime("%Y-%m-%d")

def test_process_config():
    output = workflow.process_config(config_file="tests/test_data/config")
    desired_output = {'bin_path': {'binbase': '/home/annasint/'}}
    assert output == desired_output


def test_submit_local_job():
    script = "java -jar /Users/annasintsova/tools/Trimmomatic-0.36/trimmomatic-0.36.jar " \
                      "SE /Users/annasintsova/git_repos/code/data/reads/UTI24_control.fastq "\
                  "/Users/annasintsova/git_repos/code/tests/test_data/UTI24_control_trimmed.fastq " \
            "ILLUMINACLIP:/Users/annasintsova/tools/Trimmomatic-0.36/adapters/TruSeq3-SE.fa:2:30:10:8:true" \
                  " SLIDINGWINDOW:4:15 MINLEN:40 HEADCROP:0\n"

    workflow.submit_local_job(script)
    filename = "/Users/annasintsova/git_repos/code/tests/test_data/UTI24_control_trimmed.fastq"
    assert os.path.isfile(filename)
    assert os.path.getsize(filename) == 485388774


@pytest.mark.skip(reason="only on FLUX")
def test_submit_flux_job_one_job():
    output_directory = "/scratch/hmobley_fluxod/annasint/code/tests/test_data/"
    suffix = "test_script1"
    today = dt.datetime.today().strftime("%Y-%m-%d") # todo refactor today variable
    job_name = "test_job"
    script = "mkdir TEST1"


    output = workflow.submit_flux_job(output_directory, suffix, today,
                             job_name, script)
    #assert type(output) in [str, unicode] # For python 2 (Flux)
    assert type(int(output)) == int

@pytest.mark.skip(reason="only on FLUX")
def test_submit_flux_job_two_jobs():
    # Submit first job:
    output_directory = "/scratch/hmobley_fluxod/annasint/code/tests/test_data/"
    suffix = "test_script1"
    today = dt.datetime.today().strftime("%Y-%m-%d")
    job_name = "test_job"
    script = "mkdir TEST1"

    output1 = workflow.submit_flux_job(output_directory, suffix, today,
                                      job_name, script)

    # Submit second job:
    suffix2 = 'test_script2'
    script2 = "cd TEST1\nmkdir TEST2"

    output2 = workflow.submit_flux_job(output_directory, suffix2, today,
                                       job_name, script2, job_dependency=output1)
    assert type(int(output2)) == int

# Both of these will test local system
def test_run_trim_job():

    fastq_file_input = "/Users/annasintsova/git_repos/code/data/reads/UTI24_treatment.fastq"
    output_directory = "/Users/annasintsova/git_repos/code/tests/test_data"
    today = dt.datetime.today().strftime("%Y-%m-%d")
    config_dict = workflow.process_config(config_file="local_config")
    local = True
    output_file_name = workflow.run_trim_job(fastq_file_input, output_directory,
                                             today, config_dict, local)[0]
    assert os.path.isfile(output_file_name)
# todo passes but Trimmomatic is dropping all the reads, have to figure out why
def test_run_fastqc_job():

    fastq_file_input = "/Users/annasintsova/git_repos/code/data/reads/UTI24_treatment.fastq"
    output_directory = "/Users/annasintsova/git_repos/code/tests/test_data"
    today = dt.datetime.today().strftime("%Y-%m-%d")
    config_dict = workflow.process_config(config_file="local_config")
    local = True
    actual_out_dir = workflow.run_fastqc_job(fastq_file_input, output_directory, today,
                   config_dict, local)[0]
    assert os.path.join(output_directory, "FastQC_results") == actual_out_dir
    assert len(os.listdir(actual_out_dir)) != 0
    assert os.path.isfile("/Users/annasintsova/git_repos/code/tests/"
                          "test_data/FastQC_results/UTI24_treatment_fastqc.html")

# todo make tests clean up after themselves

# this will test both on flux, plus if job dependency works properly
@pytest.mark.skip(reason="only on FLUX")
def test_run_fastqc_after_run_trim_job():
    fastq_file_input = "/scratch/hmobley_fluxod/annasint/code/data/reads/UTI24_treatment.fastq"
    output_directory = "/scratch/hmobley_fluxod/annasint/code/tests/test_data"
    today = dt.datetime.today().strftime("%Y-%m-%d")
    config_dict = workflow.process_config(config_file="config")
    local = False
    output_file_name, jobid = workflow.run_trim_job(fastq_file_input, output_directory,
                                                    today, config_dict, local)
    assert type(int(jobid)) == int #only way can figure out if the job has been submitted
    actual_out_dir, jobid2 = workflow.run_fastqc_job(output_file_name, output_directory, today,
                                             config_dict, local, job_dependency=jobid)
    assert type(int(jobid2)) == int  # todo come up with a better assert statement
    # todo run this on one of my files to make sure all is ok

# Test is passing but something is wrong with Trimmomatic run, it's dropping all the reads


if __name__ == "__main__":
    print("Hello!")