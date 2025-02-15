# -*- coding:utf-8 -*-
# Copyright (c) 2020 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import ast
import os
import argparse

import numpy as np
import paddle
import paddle.jit
import paddle.static
from paddle.inference import Config, create_predictor
from paddlehub.module.module import moduleinfo, runnable, serving

from .data_feed import reader
from .processor import postprocess, base64_to_cv2, cv2_to_base64, check_dir


@moduleinfo(
    name="dcscn",
    type="CV/image_editing",
    author="paddlepaddle",
    author_email="",
    summary="dcscn is a super resolution model.",
    version="1.1.0")
class Dcscn:
    def __init__(self):
        self.default_pretrained_model_path = os.path.join(self.directory, "dcscn_model", "model")
        self._set_config()

    def _set_config(self):
        """
        predictor config setting
        """
        model = self.default_pretrained_model_path+'.pdmodel'
        params = self.default_pretrained_model_path+'.pdiparams'
        cpu_config = Config(model, params)
        cpu_config.disable_glog_info()
        cpu_config.disable_gpu()
        self.cpu_predictor = create_predictor(cpu_config)

        try:
            _places = os.environ["CUDA_VISIBLE_DEVICES"]
            int(_places[0])
            use_gpu = True
        except:
            use_gpu = False
        if use_gpu:
            gpu_config = Config(model, params)
            gpu_config.disable_glog_info()
            gpu_config.enable_use_gpu(memory_pool_init_size_mb=1000, device_id=0)
            self.gpu_predictor = create_predictor(gpu_config)

    def reconstruct(self, images=None, paths=None, use_gpu=False, visualization=False, output_dir="dcscn_output"):
        """
        API for super resolution.

        Args:
            images (list(numpy.ndarray)): images data, shape of each is [H, W, C], the color space is BGR.
            paths (list[str]): The paths of images.
            use_gpu (bool): Whether to use gpu.
            visualization (bool): Whether to save image or not.
            output_dir (str): The path to store output images.

        Returns:
            res (list[dict]): each element in the list is a dict, the keys and values are:
                save_path (str, optional): the path to save images. (Exists only if visualization is True)
                data (numpy.ndarray): data of post processed image.
        """
        if use_gpu:
            try:
                _places = os.environ["CUDA_VISIBLE_DEVICES"]
                int(_places[0])
            except:
                raise RuntimeError(
                    "Environment Variable CUDA_VISIBLE_DEVICES is not set correctly. If you wanna use gpu, please set CUDA_VISIBLE_DEVICES as cuda_device_id."
                )

        all_data = list()
        for yield_data in reader(images, paths):
            all_data.append(yield_data)

        total_num = len(all_data)
        res = list()

        for i in range(total_num):
            image_x = np.array([all_data[i]['img_x']])
            image_x2 = np.array([all_data[i]['img_x2']])
            dropout = np.array([0])


            predictor = self.gpu_predictor if use_gpu else self.cpu_predictor
            input_names = predictor.get_input_names()
            input_handle = predictor.get_input_handle(input_names[0])
            input_handle.copy_from_cpu(image_x.copy())
            input_handle = predictor.get_input_handle(input_names[1])
            input_handle.copy_from_cpu(image_x2.copy())

            predictor.run()
            output_names = predictor.get_output_names()
            output_handle = predictor.get_output_handle(output_names[0])

            output = np.expand_dims(output_handle.copy_to_cpu(), axis=1)

            out = postprocess(
                data_out=output,
                org_im=all_data[i]['org_im'],
                org_im_shape=all_data[i]['org_im_shape'],
                org_im_path=all_data[i]['org_im_path'],
                output_dir=output_dir,
                visualization=visualization)
            res.append(out)
        return res

    @serving
    def serving_method(self, images, **kwargs):
        """
        Run as a service.
        """
        images_decode = [base64_to_cv2(image) for image in images]
        results = self.reconstruct(images=images_decode, **kwargs)
        results = [{'data': cv2_to_base64(result['data'])} for result in results]
        return results

    @runnable
    def run_cmd(self, argvs):
        """
        Run as a command.
        """
        self.parser = argparse.ArgumentParser(
            description="Run the {} module.".format(self.name),
            prog='hub run {}'.format(self.name),
            usage='%(prog)s',
            add_help=True)

        self.arg_input_group = self.parser.add_argument_group(title="Input options", description="Input data. Required")
        self.arg_config_group = self.parser.add_argument_group(
            title="Config options", description="Run configuration for controlling module behavior, not required.")
        self.add_module_config_arg()
        self.add_module_input_arg()
        args = self.parser.parse_args(argvs)
        results = self.reconstruct(
            paths=[args.input_path], use_gpu=args.use_gpu, output_dir=args.output_dir, visualization=args.visualization)
        if args.save_dir is not None:
            check_dir(args.save_dir)
            self.save_inference_model(args.save_dir)

        return results

    def add_module_config_arg(self):
        """
        Add the command config options.
        """
        self.arg_config_group.add_argument(
            '--use_gpu', type=ast.literal_eval, default=False, help="whether use GPU or not")
        self.arg_config_group.add_argument(
            '--output_dir', type=str, default='dcscn_output', help="The directory to save output images.")
        self.arg_config_group.add_argument(
            '--save_dir', type=str, default='dcscn_save_model', help="The directory to save model.")
        self.arg_config_group.add_argument(
            '--visualization', type=ast.literal_eval, default=True, help="whether to save output as images.")

    def add_module_input_arg(self):
        """
        Add the command input options.
        """
        self.arg_input_group.add_argument('--input_path', type=str, help="path to image.")


if __name__ == "__main__":
    module = Dcscn()
    #module.reconstruct(paths=["BSD100_001.png","BSD100_002.png"])
    import cv2
    img = cv2.imread("BSD100_001.png").astype('float32')
    res = module.reconstruct(images=[img])
    module.save_inference_model()
