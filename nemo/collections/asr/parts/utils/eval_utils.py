import json
import os
import subprocess
from pathlib import Path
from typing import Tuple

from omegaconf import DictConfig, OmegaConf, open_dict

from nemo.collections.asr.metrics.wer import word_error_rate_detail
from nemo.utils import logging


def run_asr_inference(cfg: DictConfig) -> DictConfig:
    if (cfg.model_path and cfg.pretrained_name) or (not cfg.model_path and not cfg.pretrained_name):
        raise ValueError("Please specify either cfg.model_path or cfg.pretrained_name!")

    if cfg.inference_mode.mode == "offline":
        cfg = run_offline_inference(cfg)

    elif cfg.inference_mode.mode == "chunked":
        if (
            "total_buffer_in_secs" not in cfg.inference_mode
            or "chunk_len_in_secs" not in cfg.inference_mode
            or not cfg.inference_mode.total_buffer_in_secs
            or not cfg.inference_mode.chunk_len_in_secs
        ):
            raise ValueError(
                f"Please specify both total_buffer_in_secs and chunk_len_in_secs for chunked inference_mode"
            )
        cfg = run_chunked_inference(cfg)

    elif cfg.inference_mode.mode == "offline_by_chunked":
        # Specify default total_buffer_in_secs=22 and chunk_len_in_secs=20 for offline conformer
        # to avoid problem of long audio sample.
        OmegaConf.set_struct(cfg, True)
        if 'total_buffer_in_secs' not in cfg.inference_mode or not cfg.inference_mode.total_buffer_in_secs:
            with open_dict(cfg):
                cfg.inference_mode.total_buffer_in_secs = 22
                logging.info(
                    f"Does not provide total_buffer_in_secs required by {cfg.inference_mode.mode} mode. Using default value {cfg.inference_mode.total_buffer_in_secs}"
                )
        if 'chunk_len_in_secs' not in cfg.inference_mode or not cfg.inference_mode.chunk_len_in_secs:
            with open_dict(cfg):
                cfg.inference_mode.chunk_len_in_secs = 20
                logging.info(
                    f"Does not provide total_buffer_in_secs required by {cfg.inference_mode.mode} mode. Using default value {cfg.inference_mode.chunk_len_in_secs}"
                )
        cfg = run_chunked_inference(cfg)

    else:
        raise ValueError(f"inference_mode could only be offline or chunked, but got {cfg.inference_mode.mode}")

    return cfg


def run_chunked_inference(cfg: DictConfig) -> DictConfig:
    if "output_filename" not in cfg or not cfg.output_filename:
        if cfg.model_path:
            model_name = Path(cfg.model_path).stem
        else:
            model_name = cfg.pretrained_name
        dataset_name = Path(cfg.test_ds.manifest_filepath).stem
        mode_name = (
            cfg.inference_mode.mode
            + "B"
            + str(cfg.inference_mode.total_buffer_in_secs)
            + "C"
            + str(cfg.inference_mode.chunk_len_in_secs)
        )

        OmegaConf.set_struct(cfg, True)
        with open_dict(cfg):
            cfg.output_filename = model_name + "-" + dataset_name + "-" + mode_name + ".json"

    script_path = (
        Path(__file__).parents[5]
        / "examples"
        / "asr"
        / "asr_chunked_inference"
        / "ctc"
        / "speech_to_text_buffered_infer_ctc.py"
    )

    if (cfg.pretrained_name and 'transducer' in cfg.pretrained_name) or (
        cfg.model_path and 'transducer' in cfg.model_path
    ):
        script_path = (
            Path(__file__).parents[5]
            / "examples"
            / "asr"
            / "asr_chunked_inference"
            / "rnnt"
            / "speech_to_text_buffered_infer_rnnt.py"
        )

    subprocess.run(
        f"python {script_path} "
        f"model_path={cfg.model_path} "
        f"pretrained_name={cfg.pretrained_name} "
        f"dataset_manifest={cfg.test_ds.manifest_filepath} "
        f"output_filename={cfg.output_filename} "
        f"batch_size={cfg.test_ds.batch_size} "
        f"chunk_len_in_secs={cfg.inference_mode.chunk_len_in_secs} "
        f"total_buffer_in_secs={cfg.inference_mode.total_buffer_in_secs} "
        f"model_stride={cfg.inference_mode.model_stride} ",
        shell=True,
        check=True,
    )
    return cfg


def run_offline_inference(cfg: DictConfig) -> DictConfig:
    if "output_filename" not in cfg or not cfg.output_filename:
        if cfg.model_path:
            model_name = Path(cfg.model_path).stem
        else:
            model_name = cfg.pretrained_name
        dataset_name = Path(cfg.test_ds.manifest_filepath).stem
        mode_name = cfg.inference_mode.mode

        OmegaConf.set_struct(cfg, True)
        with open_dict(cfg):
            cfg.output_filename = model_name + "-" + dataset_name + "-" + mode_name + ".json"

    temp_eval_config_yaml_file = "temp_eval_config.yaml"
    with open(temp_eval_config_yaml_file, "w") as f:
        OmegaConf.save(cfg, f)

    script_path = Path(__file__).parents[5] / "examples" / "asr" / "transcribe_speech.py"

    # If need to move other config such as decoding strategy, could either:
    # 1) change TranscriptionConfig on top of the executed scripts such as transcribe_speech.py in examples/asr, or
    # 2)  Add command as "rnnt_decoding.strategy=greedy_batch " to below script
    subprocess.run(
        f"python {script_path} "
        f"model_path={cfg.model_path} "
        f"pretrained_name={cfg.pretrained_name} "
        f"dataset_manifest={cfg.test_ds.manifest_filepath} "
        f"output_filename={cfg.output_filename} "
        f"batch_size={cfg.test_ds.batch_size} "
        f"eval_config_yaml={temp_eval_config_yaml_file} ",
        shell=True,
        check=True,
    )

    os.remove(temp_eval_config_yaml_file)
    return cfg


def clean_label(_str: str, num_to_words: bool = True) -> str:
    """
    Remove unauthorized characters in a string, lower it and remove unneeded spaces
    """
    replace_with_space = [char for char in '/?*\",.:=?_{|}~¨«·»¡¿„…‧‹›≪≫!:;ː→']
    replace_with_blank = [char for char in '`¨´‘’“”`ʻ‘’“"‘”']
    replace_with_apos = [char for char in '‘’ʻ‘’‘']
    _str = _str.strip()
    _str = _str.lower()
    for i in replace_with_blank:
        _str = _str.replace(i, "")
    for i in replace_with_space:
        _str = _str.replace(i, " ")
    for i in replace_with_apos:
        _str = _str.replace(i, "'")
    if num_to_words:
        _str = convert_num_to_words(_str)

    ret = " ".join(_str.split())
    return ret


def convert_num_to_words(_str: str) -> str:
    """
    Convert digits to corresponding words. Note this is a naive approach and could be replaced with text normalization.
    """
    num_to_words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
    _str = _str.strip()
    words = _str.split()
    out_str = ""
    num_word = []
    for word in words:
        if word.isdigit():
            num = int(word)
            while num:
                digit = num % 10
                digit_word = num_to_words[digit]
                num_word.append(digit_word)
                num = int(num / 10)
                if not (num):
                    num_str = ""
                    num_word = num_word[::-1]
                    for ele in num_word:
                        num_str += ele + " "
                    out_str += num_str + " "
                    num_word.clear()
        else:
            out_str += word + " "
    out_str = out_str.strip()
    return out_str


def cal_write_wer(cfg: DictConfig, pred_text_attr_name: str = None) -> Tuple[DictConfig, dict]:
    """ Calculate wer, inserion, deletion and substitution rate based on groundtruth text and pred_text_attr_name (pred_text) """
    samples = []
    hyps = []
    refs = []

    with open(cfg.engine.output_filename, 'r') as fp:
        for line in fp:
            sample = json.loads(line)

            if 'text' not in sample:
                raise ValueError(
                    "ground-truth text does not present in manifest! Cannot calculate Word Error Rate. Exiting!"
                )

            if not pred_text_attr_name:
                pred_text_attr_name = "pred_text"

            hyp = sample[pred_text_attr_name]
            ref = sample['text']

            if cfg.analyst.metric_calculator.clean_groundtruth_text:
                ref = clean_label(ref)

            wer, words, ins_rate, del_rate, sub_rate = word_error_rate_detail(
                hypotheses=[hyp], references=[ref], use_cer=cfg.analyst.metric_calculator.use_cer
            )
            sample['wer'] = wer
            sample['words'] = words
            sample['ins_rate'] = ins_rate
            sample['del_rate'] = del_rate
            sample['sub_rate'] = sub_rate

            samples.append(sample)
            hyps.append(hyp)
            refs.append(ref)

    total_wer, total_words, total_ins_rate, total_del_rate, total_sub_rate = word_error_rate_detail(
        hypotheses=hyps, references=refs, use_cer=cfg.analyst.metric_calculator.use_cer
    )

    if "output_filename" not in cfg.analyst.metric_calculator or not cfg.analyst.metric_calculator.output_filename:
        # overwrite the current generated manifest
        OmegaConf.set_struct(cfg, True)
        with open_dict(cfg):
            cfg.analyst.metric_calculator.output_filename = cfg.engine.output_filename

    with open(cfg.analyst.metric_calculator.output_filename, 'w') as fout:
        for sample in samples:
            json.dump(sample, fout)
            fout.write('\n')
            fout.flush()

    total_res = {
        "samples": len(samples),
        "words": total_words,
        "wer": total_wer,
        "ins_rate": total_ins_rate,
        "del_rate": total_del_rate,
        "sub_rate": total_sub_rate,
    }
    return cfg, total_res


def target_metadata_wer(manifest: str, target: str, meta_cfg: DictConfig, eval_metric: str = "wer",) -> dict:
    """ 
    Calculate group eval_metric (wer) for target metadata, 
    such as wer for female/male or slot group wer for 0-2s, 2-5s, >5s audios 
    """
    wer_each_class = {}
    with open(manifest, 'r') as fp:
        for line in fp:
            sample = json.loads(line)
            if target in sample:
                target_class = sample[target]
                if target_class not in wer_each_class:
                    wer_each_class[target_class] = {
                        'samples': 0,
                        'words': 0,
                        "errors": 0,
                        "inss": 0,
                        "dels": 0,
                        "subs": 0,
                    }
                wer_each_class[target_class]['samples'] += 1

                words = sample["words"]
                wer_each_class[target_class]["words"] += words
                wer_each_class[target_class]["errors"] += words * sample[eval_metric]
                wer_each_class[target_class]["inss"] += words * sample["ins_rate"]
                wer_each_class[target_class]["dels"] += words * sample["del_rate"]
                wer_each_class[target_class]["subs"] += words * sample["sub_rate"]

    if len(wer_each_class) > 0:
        res_wer_each_class = {}
        for target_class in wer_each_class:
            res_wer_each_class[target_class] = {}
            res_wer_each_class[target_class]["samples"] = wer_each_class[target_class]["samples"]
            res_wer_each_class[target_class]["wer"] = (
                wer_each_class[target_class]["errors"] / wer_each_class[target_class]["words"]
            )
            res_wer_each_class[target_class]["words"] = wer_each_class[target_class]["words"]
            res_wer_each_class[target_class]["ins_rate"] = (
                wer_each_class[target_class]["inss"] / wer_each_class[target_class]["words"]
            )
            res_wer_each_class[target_class]["del_rate"] = (
                wer_each_class[target_class]["dels"] / wer_each_class[target_class]["words"]
            )
            res_wer_each_class[target_class]["sub_rate"] = (
                wer_each_class[target_class]["subs"] / wer_each_class[target_class]["words"]
            )
    else:
        logging.info(f"metadata '{target}' does not present in manifest. Skipping! ")
        return None

    values = ['samples', 'words', 'errors', 'inss', 'dels', 'subs']
    slot_wer = {}
    if 'slot' in meta_cfg and meta_cfg.slot:
        for target_class in wer_each_class:
            for s in meta_cfg.slot:
                if isinstance(s[0], float) or isinstance(s[0], int):
                    if s[0] <= target_class < s[1]:
                        slot_key = "slot-" + ",".join(str(i) for i in s)
                        if slot_key not in slot_wer:
                            slot_wer[slot_key] = {
                                'samples': 0,
                                'words': 0,
                                "errors": 0,
                                "inss": 0,
                                "dels": 0,
                                "subs": 0,
                            }

                        for v in values:
                            slot_wer[slot_key][v] += wer_each_class[target_class][v]
                        break

                elif isinstance(s[0], str):
                    if target_class in s:
                        slot_key = "slot-" + ",".join(s)
                        if slot_key not in slot_wer:
                            slot_wer[slot_key] = {
                                'samples': 0,
                                'words': 0,
                                "errors": 0,
                                "inss": 0,
                                "dels": 0,
                                "subs": 0,
                            }

                        for v in values:
                            slot_wer[slot_key][v] += wer_each_class[target_class][v]
                        break
                else:
                    raise ValueError("Current only support target metadata belongs to numeric or string ")

        for slot_key in slot_wer:
            slot_wer[slot_key]['wer'] = slot_wer[slot_key]['errors'] / slot_wer[slot_key]['words']
            slot_wer[slot_key]['ins_rate'] = slot_wer[slot_key]['inss'] / slot_wer[slot_key]['words']
            slot_wer[slot_key]['del_rate'] = slot_wer[slot_key]['dels'] / slot_wer[slot_key]['words']
            slot_wer[slot_key]['sub_rate'] = slot_wer[slot_key]['subs'] / slot_wer[slot_key]['words']
            slot_wer[slot_key].pop('errors')
            slot_wer[slot_key].pop('inss')
            slot_wer[slot_key].pop('dels')
            slot_wer[slot_key].pop('subs')
        res_wer_each_class.update(slot_wer)

    if meta_cfg.wer_each_class:
        ret = res_wer_each_class

    if (not meta_cfg.wer_each_class) and ('slot' in meta_cfg and meta_cfg.slot):
        ret = slot_wer

    return ret
