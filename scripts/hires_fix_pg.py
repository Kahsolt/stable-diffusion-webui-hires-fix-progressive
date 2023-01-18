from PIL.Image import Image
from typing import List

import gradio as gr
import numpy as np

from modules.scripts import Script
from modules.shared import state, sd_upscalers 
from modules.processing import process_images, StableDiffusionProcessingTxt2Img, StableDiffusionProcessingImg2Img, Processed
from modules.images import resize_image

DEFAULT_TARGET_WIDTH  = 1024
DEFAULT_TARGET_HEIGHT = 1024
DEFAULT_ITER          = 2
DEFAULT_STEP          = 30
DEFAULT_DENOISE_W     = 0.5
DEFAULT_ALTER_PROMPT  = None
DEFAULT_UPSCALER      = 'Lanczos'
DEFAULT_RESIZE_MODE   = 'Adjust'
DEFAULT_SAVE_INTERM   = False

CHOICE_UPSCALER    = [x.name for x in sd_upscalers if x.name not in [None, 'None']]
CHOICE_RESIZE_MODE = ['Adjust', 'Crop', 'Fill']


def txt2img_to_img2img(p:StableDiffusionProcessingTxt2Img) -> StableDiffusionProcessingImg2Img:
    KNOWN_KEYS = [      # see `StableDiffusionProcessing.__init__()`
        'sd_model',
        'outpath_samples',
        'outpath_grids',
        'prompt',
        'styles',
        'seed',
        'subseed',
        'subseed_strength',
        'seed_resize_from_h',
        'seed_resize_from_w',
        'seed_enable_extras',
        'sampler_name',
        'batch_size',
        'n_iter',
        'steps',
        'cfg_scale',
        'width',
        'height',
        'restore_faces',
        'tiling',
        'do_not_save_samples',
        'do_not_save_grid',
        'extra_generation_params',
        'overlay_images',
        'negative_prompt',
        'eta',
        'do_not_reload_embeddings',
        'denoising_strength',
        'ddim_discretize',
        's_churn',
        's_tmax',
        's_tmin',
        's_noise',
        'override_settings',
        'override_settings_restore_afterwards',
        'sampler_index',
        'script_args',
    ]
    kwargs = { k: getattr(p, k) for k in dir(p) if k in KNOWN_KEYS }    # inherit params
    return StableDiffusionProcessingImg2Img(**kwargs)


class Script(Script):

    def title(self):
        return 'Hires.fix Progressive'

    def describe(self):
        return "A progressive version of hires.fix implementation."

    def show(self, is_img2img):
        return not is_img2img

    def ui(self, is_img2img):
        with gr.Row():
            upscaler      = gr.Dropdown(label='Upscaler',    value=lambda: DEFAULT_UPSCALER,    choices=CHOICE_UPSCALER)
            resize_mode   = gr.Dropdown(label='Resize mode', value=lambda: DEFAULT_RESIZE_MODE, choices=CHOICE_RESIZE_MODE)
            target_width  = gr.Slider(label='Target width',  value=lambda: DEFAULT_TARGET_WIDTH,  minimum=512, maximum=2048, step=8)
            target_height = gr.Slider(label='Target height', value=lambda: DEFAULT_TARGET_HEIGHT, minimum=512, maximum=2048, step=8)

        with gr.Group():
            with gr.Row():
                iters = gr.Slider(label='Iteration', value=lambda: DEFAULT_ITER, minimum=0, maximum=30, step=1)
                steps = gr.Slider(label='Img2img steps (per iter)', value=lambda: DEFAULT_STEP, minimum=1, maximum=150, step=1)
                denoising_strength = gr.Slider(label='Denoising strength', value=lambda: DEFAULT_DENOISE_W, minimum=0.0, maximum=1.0, step=0.01)
            with gr.Row():
                alter_prompt = gr.TextArea(label='Img2img prompt', value=lambda: DEFAULT_ALTER_PROMPT, lines=2)
        
        with gr.Row():
            save_interm = gr.Checkbox(label='Save intermediate images', value=lambda: DEFAULT_SAVE_INTERM)

        return [iters, 
                upscaler, resize_mode, target_width, target_height,
                steps, denoising_strength, alter_prompt,
                save_interm]

    def run(self, p:StableDiffusionProcessingTxt2Img, 
            iters:int, 
            upscaler:str, resize_mode:str, target_width:int, target_height:int, 
            steps:int, denoising_strength:float, alter_prompt:str,
            save_interm:bool):

        if 'force disable original hires.fix':
            p.enable_hr = False
            p.denoising_strength = None
            p.extra_generation_params.pop("Hires upscale", None)
            p.extra_generation_params.pop("Hires resize",  None)

        if 'reuse to fix violate things':
            seed = p.seed
            subseed = p.subseed
            subseed_strength = p.subseed_strength

        images: List[Image] = []

        ''' Txt2Img '''
        if not save_interm:
            p.do_not_save_grid    = iters > 0
            p.do_not_save_samples = iters > 0
        proc = process_images(p)
        info: str = proc.info
        imgs = proc.images
        images.extend(imgs)

        resize_mode: int = CHOICE_RESIZE_MODE.index(resize_mode)
        widths:  np.array = np.linspace(p.width,  target_width , iters + 1)[1:].round().astype(int)
        heights: np.array = np.linspace(p.height, target_height, iters + 1)[1:].round().astype(int)
        
        state.nextjob()

        p:StableDiffusionProcessingImg2Img = txt2img_to_img2img(p)
        p.steps = int(steps / denoising_strength)       # NOTE: to work alike original hires.fix
        p.prompt = alter_prompt or p.prompt
        p.denoising_strength = denoising_strength
        p.resize_mode = resize_mode

        for i in range(iters):
            if state.interrupted: break

            ''' Upscale '''
            imgs = [resize_image(resize_mode, img, widths[i], heights[i], upscaler_name=upscaler) for img in imgs]

            if steps <= 0: continue     # upscale only, no img2img

            ''' Img2Img '''
            rw, rh = imgs[0].size
            p.width  = rw
            p.height = rh
            p.init_images = imgs
            p.seed = seed
            p.subseed = subseed
            p.subseed_strength = subseed_strength

            if not save_interm:
                p.do_not_save_grid    = i < iters - 1
                p.do_not_save_samples = i < iters - 1
            proc = process_images(p)
            info = proc.info
            imgs = proc.images
            images.extend(imgs)

        ret_imgs = images if save_interm else imgs

        return Processed(p, ret_imgs, p.seed, info)
