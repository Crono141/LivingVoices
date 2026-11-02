"""Delivery scores for rendered lines (2026-10-12, test): audEERING's dimensional emotion model (wav2vec 2.0 fine-tuned
on MSP-Podcast; CC BY-NC-SA 4.0 -- fine for a private, unsold realm) gives each clip arousal (energy), dominance
(assertiveness) and valence (positivity), roughly 0..1. It never sees the text: it says how the take SOUNDS, which is
then compared with what the director asked for (intensity, style).
  CUDA_VISIBLE_DEVICES=1 ~/ComfyUI/venv/bin/python ../tools/delivery_score.py <label=file.mp3> ...
"""
import subprocess, sys
import lvconfig as LV
import numpy as np, torch, torch.nn as nn
from transformers import Wav2Vec2Processor
from transformers.models.wav2vec2.modeling_wav2vec2 import Wav2Vec2Model, Wav2Vec2PreTrainedModel
MODEL = f'{LV.MODELS}/classifiers/audeering-w2v2-msp-dim'

class RegressionHead(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.dense = nn.Linear(config.hidden_size, config.hidden_size)
        self.dropout = nn.Dropout(config.final_dropout)
        self.out_proj = nn.Linear(config.hidden_size, config.num_labels)
    def forward(self, x):
        return self.out_proj(self.dropout(torch.tanh(self.dense(self.dropout(x)))))

class EmotionModel(Wav2Vec2PreTrainedModel):   # as on the model card
    def __init__(self, config):
        super().__init__(config)
        self.config = config
        self.wav2vec2 = Wav2Vec2Model(config)
        self.classifier = RegressionHead(config)
        self.init_weights()
    def forward(self, input_values):
        hidden = self.wav2vec2(input_values)[0].mean(dim=1)
        return self.classifier(hidden)

def load(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '1', '-ar', '16000', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)

proc = Wav2Vec2Processor.from_pretrained(MODEL)
model = EmotionModel.from_pretrained(MODEL, use_safetensors=True).to('cuda').eval()

def score(path):
    y = load(path)
    x = proc(y, sampling_rate=16000)['input_values'][0].reshape(1, -1)
    with torch.no_grad():
        a, d, v = model(torch.from_numpy(x).to('cuda'))[0].tolist()
    return a, d, v, len(y) / 16000

if __name__ == '__main__':
    print(f"{'take':44s} {'arousal':>8s} {'dominance':>9s} {'valence':>8s} {'secs':>5s}")
    for arg in sys.argv[1:]:
        label, _, path = arg.partition('=')
        a, d, v, s = score(path)
        print(f'{label:44s} {a:8.3f} {d:9.3f} {v:8.3f} {s:5.1f}')
