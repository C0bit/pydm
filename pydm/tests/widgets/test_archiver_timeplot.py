import numpy as np
import pytest
from qtpy.QtCore import Slot

from ..conftest import ConnectionSignals
from ...widgets.archiver_time_plot import ArchivePlotCurveItem, PyDMArchiverTimePlot, FormulaCurveItem


@pytest.mark.parametrize("address", ["ca://LINAC:PV1", "pva://LINAC:PV1", "LINAC:PV1"])
def test_set_archive_channel(address):
    """Verify the address for the archiver data plugin is set correctly for all possible EPICS address prefixes"""
    curve_item = ArchivePlotCurveItem(channel_address=address)
    assert curve_item.archive_channel.address == "archiver://pv=LINAC:PV1"


def test_receive_archive_data(signals: ConnectionSignals):
    """Ensure data from archiver appliance is inserted into the archive buffer correctly"""
    curve_item = ArchivePlotCurveItem()
    curve_item.setBufferSize(20)
    curve_item.setArchiveBufferSize(20)

    # We start with a data buffer with some sample values like those generated by a running time plot
    # The x-values are timestamps and the y-values are samples from a PV
    example_live_data = np.array([[100, 101, 102, 103, 104, 105], [2.15, 2.20, 2.25, 2.22, 2.20, 2.18]])
    starting_data = np.concatenate((np.zeros((2, curve_item.getBufferSize() - 6)), example_live_data), axis=1)
    curve_item.points_accumulated += 6
    curve_item.data_buffer = starting_data

    # A quick check to make sure we're starting off correctly
    assert (2, 20) == curve_item.data_buffer.shape

    signals.new_value_signal[np.ndarray].connect(curve_item.receiveArchiveData)

    # First test the most basic case, where we've requested a bit of archive data right before the live data
    mock_archive_data = np.array([[70, 75, 80, 85, 90, 95], [2.05, 2.08, 2.07, 2.08, 2.12, 2.14]])
    signals.new_value_signal[np.ndarray].emit(mock_archive_data)

    expected_data = np.zeros((2, 14))
    expected_data = np.concatenate((expected_data, mock_archive_data), axis=1)

    # Confirm the archive data was inserted as expected
    assert np.array_equal(curve_item.archive_data_buffer, expected_data)


def test_insert_archive_data():
    """When first receiving large amounts of data from the archiver appliance, it will be of the 'optimized' form
    in which it is sampled across a fixed number of bins. Drawing a zoom box in this data will get more detailed
    data which must be inserted into the archive data buffer. This tests that insertion is successful."""
    curve_item = ArchivePlotCurveItem()
    curve_item.setBufferSize(10)
    curve_item.setArchiveBufferSize(10)

    # Need some initial data in the live data buffer so that the archive data gets inserted into the proper place
    curve_item.data_buffer = np.array([[130, 140], [8, 9]])
    curve_item.points_accumulated = 2

    # Set up a sample archive buffer
    curve_item.archive_data_buffer = np.array(
        [[0, 0, 0, 0, 100, 105, 110, 115, 120, 125], [0, 0, 0, 0, 2, 3, 4, 5, 6, 7]], dtype=float
    )

    curve_item.archive_points_accumulated = 6
    curve_item.zoomed = True

    # Receive raw data that is more detailed than the two values it will be replacing
    mock_archive_data = np.array([[104, 106, 108, 111], [2.8, 3.1, 3.7, 3.95]])

    curve_item.insert_archive_data(mock_archive_data)

    # The original average values for timestamps 105 and 106 should now be replace with the actual PV data
    expected_data = np.array([[0, 0, 100, 104, 106, 108, 111, 115, 120, 125], [0, 0, 2, 2.8, 3.1, 3.7, 3.95, 5, 6, 7]])

    assert np.array_equal(curve_item.archive_data_buffer, expected_data)


def test_archive_buffer_full():
    """If we insert more data points than the archive buffer can hold, then the oldest points are
    removed in favor of the new ones until the user requests further backfill data again"""
    curve_item = ArchivePlotCurveItem()
    curve_item.setBufferSize(6)
    curve_item.setArchiveBufferSize(6)
    curve_item.data_buffer = np.array([[130, 140], [8, 9]])
    curve_item.points_accumulated = 2

    # Set up a sample archive buffer that is already full
    curve_item.archive_data_buffer = np.array([[100, 105, 110, 115, 120, 125], [2, 3, 4, 5, 6, 7]], dtype=float)
    curve_item.archive_points_accumulated = 6
    curve_item.zoomed = True

    # Receive data that will cause that will not fit in the buffer without deleting other data points
    mock_archive_data = np.array([[104, 106, 108], [2.8, 3.1, 3.7]])

    curve_item.insert_archive_data(mock_archive_data)

    # This is what is left over after the oldest data points have been trimmed
    expected_data = np.array([[104, 106, 108, 115, 120, 125], [2.8, 3.1, 3.7, 5, 6, 7]])

    assert np.array_equal(curve_item.archive_data_buffer, expected_data)


@Slot(float, float, str)
def inspect_data_request(min_x: float, max_x: float, processing_command: str):
    """Simple helper function to store the signal parameters it was invoked with"""
    inspect_data_request.min_x = min_x
    inspect_data_request.max_x = max_x
    inspect_data_request.processing_command = processing_command


def test_request_data_from_archiver(qtbot):
    """Test that the signal requesting data from the archiver appliance is built correctly"""

    # Create a plot and its associated curve item
    plot = PyDMArchiverTimePlot(optimized_data_bins=10)
    curve_item = ArchivePlotCurveItem()
    # Connect to the helper function above to allow for inspection of the parameters the signal was invoked with
    curve_item.archive_data_request_signal.connect(inspect_data_request)
    plot._curves.append(curve_item)

    # Request data from a short 100 second period
    plot._archive_request_queued = True
    plot.requestDataFromArchiver(100, 200)

    # Verify that the data is requested for the time period specified, and since it is only 100 seconds, it is raw data
    assert inspect_data_request.min_x == 100
    assert inspect_data_request.max_x == 199
    assert inspect_data_request.processing_command == ""

    # Now request over a day's worth of data at once. This will cause the request to be for optimized data
    # returned in 10 bins as specified by the "optimized_data_bins" param above
    plot._archive_request_queued = True
    plot.requestDataFromArchiver(100, 100000)
    assert inspect_data_request.min_x == 100
    assert inspect_data_request.max_x == 99999
    assert inspect_data_request.processing_command == "optimized_10"

    # Finally let's do a test without specifying min_x and max_x to test the plot's logic of determining
    # these values itself

    # Create a small data buffer for the plot's curve representing live data visible on the plot
    curve_item.points_accumulated = 3
    curve_item._bufferSize = 5
    # Index 0 represents timestamps, index 1 the associated values. So observations were made at time 300, 301, 302.
    curve_item.data_buffer = np.array([[0, 0, 300, 301, 302], [0, 0, 1.5, 1.6, 1.5]])

    plot._min_x = 50  # This is the minimum timestamp visible on the x-axis, representing what the user panned to
    plot._archive_request_queued = True
    plot.requestDataFromArchiver()
    # The min_x requested should have defaulted to 50 since that is what the user requested as mentioned above
    assert inspect_data_request.min_x == 50
    # Because the oldest live timestamp in the data buffer was 300, the ending timestamp for the request should
    # be one less than that.
    assert inspect_data_request.max_x == 299


def test_formula_curve_item():
    # Create two ArchivePlotCurveItems which we will make a few formulas out of
    # Assume the curves have live and archive connections
    curve_item1 = ArchivePlotCurveItem()
    curve_item1.archive_data_buffer = np.array([[100, 105, 110, 115, 120, 125], [2, 3, 4, 5, 6, 7]], dtype=float)
    curve_item1.archive_points_accumulated = 6
    curve_item1.connected = True
    curve_item1.arch_connected = True

    curve_item2 = ArchivePlotCurveItem()
    curve_item2.archive_data_buffer = np.array([[101, 106, 111, 116, 121, 126], [1, 2, 3, 4, 5, 6]], dtype=float)
    curve_item2.archive_points_accumulated = 6
    curve_item2.connected = True
    curve_item2.arch_connected = True

    # Dictionary of PVS
    curves1 = dict()
    curves1["A"] = curve_item1
    curves2 = dict()
    curves2["A"] = curve_item1
    curves2["B"] = curve_item2

    formula1 = r"f://5*{A}"
    formula2 = r"f://log({A})"
    formula3 = r"f://{A}+{B}"
    formula4 = r"f://{A}*{B}"

    # Create the curves with the correct inputs
    formula_curve_1 = FormulaCurveItem(formula=formula1, pvs=curves1)
    formula_curve_2 = FormulaCurveItem(formula=formula2, pvs=curves1)
    formula_curve_3 = FormulaCurveItem(formula=formula3, pvs=curves2)
    formula_curve_4 = FormulaCurveItem(formula=formula4, pvs=curves2)

    expected1 = np.array([[100, 105, 110, 115, 120, 125], [10, 15, 20, 25, 30, 35]], dtype=float)
    expected2 = np.array([[100, 105, 110, 115, 120, 125], np.log([2, 3, 4, 5, 6, 7])], dtype=float)
    expected3 = np.array(
        [[101, 105, 106, 110, 111, 115, 116, 120, 121, 125], [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]], dtype=float
    )
    expected4 = np.array(
        [[101, 105, 106, 110, 111, 115, 116, 120, 121, 125], [2, 3, 6, 8, 12, 15, 20, 24, 30, 35]], dtype=float
    )

    # Evaluate them all
    formula_curve_1.evaluate()
    formula_curve_2.evaluate()
    formula_curve_3.evaluate()
    formula_curve_4.evaluate()

    # They should match our precalculated outcomes
    assert np.array_equal(formula_curve_1.archive_data_buffer, expected1)
    assert np.array_equal(formula_curve_2.archive_data_buffer, expected2)
    assert np.array_equal(formula_curve_3.archive_data_buffer, expected3)
    assert np.array_equal(formula_curve_4.archive_data_buffer, expected4)

def test_disconnected_formula_curve_item():
    # Create a connected ArchivePlotCurveItem
    connected_curve = ArchivePlotCurveItem()
    connected_curve.archive_data_buffer = np.array([[100, 105, 110, 115, 120, 125], [2, 3, 4, 5, 6, 7]], dtype=float)
    connected_curve.archive_points_accumulated = 6
    connected_curve.connected = True
    connected_curve.arch_connected = True

    # Create a disconnected ArchivePlotCurveItem
    disconnected_curve = ArchivePlotCurveItem()
    disconnected_curve.archive_data_buffer = np.array([[101, 106, 111, 116, 121, 126], [1, 2, 3, 4, 5, 6]], dtype=float)
    disconnected_curve.archive_points_accumulated = 6
    disconnected_curve.connected = False
    disconnected_curve.arch_connected = False

    # Create a disconnected FormulaCurveItem
    disconnected_formula = FormulaCurveItem(formula="")
    disconnected_formula.archive_data_buffer = np.array([[101, 106, 111, 116, 121, 126], [1, 2, 3, 4, 5, 6]], dtype=float)
    disconnected_formula.archive_points_accumulated = 6
    disconnected_formula.connected = False
    disconnected_formula.arch_connected = False

    formula = r"f://{A}+{B}"

    # Create FormulaCurve using the 2 curves
    # This formula curve should be disconnected
    pv_dict = dict()
    pv_dict["A"] = connected_curve
    pv_dict["B"] = disconnected_curve

    formula_curve_1 = FormulaCurveItem(formula=formula, pvs=pv_dict)

    # Create FormulaCurve using the connected curve and the disconnected formula curve
    # This formula curve should be disconnected
    pv_dict = dict()
    pv_dict["A"] = connected_curve
    pv_dict["B"] = disconnected_formula

    formula_curve_2 = FormulaCurveItem(formula=formula, pvs=pv_dict)

    formula_curve_1.evaluate()
    formula_curve_2.evaluate()

    # Both curves should have no data
    assert np.array_equal(formula_curve_1.archive_data_buffer, np.zeros((2, 0), dtype=float))
    assert np.array_equal(formula_curve_2.archive_data_buffer, np.zeros((2, 0), dtype=float))
