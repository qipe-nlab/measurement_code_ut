from logging import getLogger
import os
import time
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
from measurement_codes_ut.fitting.qubit_spectral import QubitSpectral

logger = getLogger(__name__)


class FindGFPeak(object):
    experiment_name = "FindGFPeak"
    input_parameters = [
        "cavity_readout_sequence_amplitude_expected_sn",
        "cavity_readout_trigger_delay",
        "cavity_dressed_frequency",
        "qubit_dressed_frequency",
        "qubit_control_amplitude",
        "cavity_readout_skew",
        "readout_pulse_length"
    ]
    output_parameters = [
        "qubit_dressed_frequency_gf",
        "qubit_anharmonicity",
    ]

    def __init__(self, num_shot=1000, repetition_margin=50e3, expected_anharmonicity=-350e6, sweep_range=200e6, sweep_step=101, qubit_pump_amplitude=0.2):
        self.dataset = None
        self.num_shot = num_shot
        self.expected_anharmonicity = expected_anharmonicity
        self.sweep_range = sweep_range
        self.sweep_step = sweep_step
        self.qubit_pump_amplitude = qubit_pump_amplitude
        self.repetition_margin = repetition_margin
        if expected_anharmonicity >= 0:
            logger.warning(
                "Anharmonicity is typically defined as a negative value, but positive frequency is provided. Is it expeceted process?")

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

        readout_port = tdm.port['readout'].port
        acq_port = tdm.acquire_port['readout_acquire']
        qubit_port = tdm.port['qubit'].port

        ports = [readout_port, qubit_port, acq_port]

        tdm.set_acquisition_delay(note.cavity_readout_trigger_delay)
        tdm.set_repetition_margin(self.repetition_margin)
        tdm.set_shots(self.num_shot)
        tdm.set_acquisition_mode(averaging_waveform=True, averaging_shot=True)

        readout_freq = note.cavity_dressed_frequency

        qubit_freq = note.qubit_dressed_frequency

        tdm.port['readout'].frequency = readout_freq

        expected_qubit_frequency_gf = note.qubit_dressed_frequency + \
            self.expected_anharmonicity / 2.
        shift = np.linspace(-self.sweep_range / 2,
                            self.sweep_range / 2, self.sweep_step)

        seq = Sequence(ports)
        seq.add(Square(amplitude=self.qubit_pump_amplitude, duration=10000),
                qubit_port, copy=False)
        seq.trigger(ports)
        seq.add(Delay(note.cavity_readout_skew), readout_port)
        seq.add(Delay(note.cavity_readout_skew), acq_port)       
        seq.add(ResetPhase(phase=0), readout_port, copy=False) 
        seq.add(Square(amplitude=note.cavity_readout_sequence_amplitude_expected_sn, duration=note.readout_pulse_length),
                readout_port, copy=False)
        seq.add(Acquire(duration=note.readout_pulse_length), acq_port)

        seq.trigger(ports)

        tdm.port['qubit'].frequency = expected_qubit_frequency_gf + shift

        tdm.sequence = seq
        tdm.variables = None

        dataset = tdm.take_data(dataset_name=self.__class__.experiment_name, as_complex=False, exp_file=__file__)
        return dataset

    def analyze(self, dataset, note, savefig=False, savepath="./fig"):

        freq = dataset.data["qubit_LO_frequency"]["values"]
        response = dataset.data["readout_acquire"]["values"]

        expected_gf_freq = note.qubit_dressed_frequency + self.expected_anharmonicity/2.

        # fit
        pca = PCA()
        projected = pca.fit_transform(response)
        component = projected[:, 0]

        model = QubitSpectral()
        model.fit(freq, component)

        fitting_parameter_list = [
            "qubit_peak_height",
            "qubit_dressed_frequency_gf",
            "qubit_full_linewidth",
            "base_amplitude",
        ]
        for index, item in enumerate(fitting_parameter_list):
            name = item
            value = model.param_list[index]
            value_error = model.param_error_list[index]
            setattr(self, name, value)
            setattr(self, name+"_stderr", value_error)

        ##### plot #####
        fit_slice = 1001
        component_fit = model.predict(
            np.linspace(min(freq), max(freq), fit_slice))

        self.data_label = dataset.path.split("/")[-1][27:]
        plot = PlotHelper(f"{self.data_label}", 1, 3)
        plot.plot_complex(response[:, 0] + 1.j *
                          response[:, 1], line_for_data=True)
        plot.label("I", "Q")

        plot.change_plot(0, 1)
        plot.plot_fitting(freq, projected[:, 0], label="PCA")
        plot.plot_fitting(freq, projected[:, 1], label="perp-PCA")
        plot.label("Drive frequency (Hz)", "Response")

        plot.change_plot(0, 2)
        plot.plot_fitting(freq, component, y_fit=component_fit, label="PCA")
        plot.label("Drive frequency (Hz)", "Response")
        plt.tight_layout()
        if savefig:
            plt.savefig(f"{savepath}/{self.data_label}.png")
        plt.show()
        ##### plot #####

        experiment_note = AttributeDict()
        experiment_note.qubit_dressed_frequency_gf = self.qubit_dressed_frequency_gf
        experiment_note.qubit_anharmonicity = 2 * \
            (self.qubit_dressed_frequency_gf - note.qubit_dressed_frequency)
        note.add_experiment_note(self.__class__.experiment_name,
                                 experiment_note, self.__class__.output_parameters,)

    def report_stat(self):
        pass

    def report_visualize(self, dataset, note):
        pass
