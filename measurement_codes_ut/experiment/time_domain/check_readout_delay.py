
from logging import getLogger
import os
import numpy as np
import matplotlib.pyplot as plt
from plottr.data.datadict_storage import DataDict, DDH5Writer
from sklearn.decomposition import PCA
from tqdm import tqdm

from measurement_codes_ut.measurement_tool.wrapper import AttributeDict
from sequence_parser import Port, Sequence
from sequence_parser.instruction import *

from measurement_codes_ut.helper.plot_helper import PlotHelper
from plottr.data.datadict_storage import datadict_from_hdf5

logger = getLogger(__name__)


class CheckReadoutDelay(object):
    experiment_name = "CheckReadoutDelay"
    input_parameters = [
        "cavity_readout_sequence_amplitude_expected_sn",
        "cavity_dressed_frequency_cw",
        "readout_pulse_length"
    ]
    output_parameters = [
        "cavity_readout_trigger_delay",
    ]

    def __init__(self, num_shot=1000, repetition_margin=50e3,):
        self.dataset = None
        self.num_shot = num_shot
        self.repetition_margin = repetition_margin

    def execute(self, tdm, calibration_notes,
                update_experiment=True, update_analyze=True):
        if update_experiment:
            self.dataset = self.take_data(tdm, calibration_notes)

        if update_analyze:
            if self.dataset is None:
                raise ValueError("Data is not taken yet.")
            self.analyze(self.dataset, calibration_notes)

        return self.dataset

    def take_data(self, tdm, calibaration_note):
        note = calibaration_note.get_calibration_parameters(
            self.__class__.experiment_name, self.__class__.input_parameters)

        readout_freq = note.cavity_dressed_frequency_cw

        readout_port = tdm.port['readout'].port
        self.r_if = readout_port.if_freq
        acq_port = tdm.acquire_port['readout_acquire']
        qubit_port = tdm.port['qubit'].port

        tdm.port['readout'].frequency = readout_freq - 100e6

        ports = [readout_port, qubit_port, acq_port]

        tdm.set_repetition_margin(self.repetition_margin)
        tdm.set_acquisition_delay(0)
        tdm.set_shots(self.num_shot)
        tdm.set_acquisition_mode(averaging_waveform=False, averaging_shot=True)

        seq = Sequence(ports)
        seq.add(ResetPhase(phase=0), readout_port, copy=False)
        seq.trigger(ports)
        seq.add(Square(amplitude=note.cavity_readout_sequence_amplitude_expected_sn, duration=note.readout_pulse_length),
                readout_port, copy=False)
        seq.add(Acquire(duration=note.readout_pulse_length), acq_port)
        # seq.draw()
        seq.trigger(ports)

        tdm.sequence = seq
        tdm.variables = None

        dataset = tdm.take_data(dataset_name=self.__class__.experiment_name, as_complex=False, exp_file=__file__)
        return dataset

    # override
    def analyze(self, dataset, calibration_note, savefig=True, savepath="./fig"):
        time = np.arange(1000)*2
        signal = dataset.data["readout_acquire"]["values"]
        ma_length = int(1/self.r_if)
        convolve_length = int(max(time)/20)
        # print(convolve_length)

        self.data_label = dataset.path.split("/")[-1][27:]

        # analysis
        pca_model = PCA()
        projected = pca_model.fit_transform(signal)
        component = projected[:, 0]
        convolve_window = np.ones(convolve_length)/convolve_length
        convolve_cut = convolve_length//2
        smoothed = np.convolve(component, convolve_window, "valid")
        valid_time = time[convolve_cut: convolve_cut + len(smoothed)]
        abs_grad_smoothed = np.abs(np.gradient(smoothed))
        delay_time_index = np.argmax(abs_grad_smoothed)
        delay_time = time[delay_time_index + convolve_cut]
        # print(delay_time)
        cavity_readout_trigger_delay = delay_time

        signal_ma_i = np.convolve(
            signal[:, 0], np.ones(ma_length)/ma_length, "valid")
        signal_ma_q = np.convolve(
            signal[:, 1], np.ones(ma_length)/ma_length, "valid")

        plot = PlotHelper(title=f"{self.data_label}", columns=1)
        # plot.plot(time, signal[:, 0], label="I")
        # plot.plot(time, signal[:, 1], label="Q")
        plot.plot(time[ma_length-1:], signal_ma_i, label="I")
        plot.plot(time[ma_length-1:], signal_ma_q, label="Q")
        plt.axvline(delay_time, label='start point',
                    ls='-', color='black', lw=3)
        # plot.plot([delay_time, delay_time], [np.min(projected),
        #           np.max(projected)], label="start point")
        plot.label("Time (ns)", "Response")
        plt.tight_layout()
        # plot.change_plot(0, 1)
        # plot.plot(time, projected[:, 0], label="PCA")
        # plot.plot(time, projected[:, 1], label="anti-PCA")
        # plot.plot([delay_time, delay_time], [np.min(projected),
        #           np.max(projected)], label="start point")
        # plot.label("Time (ns)", "response")

        if savefig:
            os.makedirs(savepath, exist_ok=True)
            plt.savefig(f"{savepath}/{self.data_label}.png",
                        bbox_inches='tight')
        plt.show()

        experiment_note = AttributeDict()
        experiment_note.cavity_readout_trigger_delay = cavity_readout_trigger_delay*1.0
        calibration_note.add_experiment_note(
            self.__class__.experiment_name, experiment_note, self.__class__.output_parameters,)

    # override

    def report_stat(self):
        pass

    # override
    def report_visualize(self, dataset, note):
        pass
