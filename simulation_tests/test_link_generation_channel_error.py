from .utils import Worker
import pytest


@pytest.mark.asyncio
async def test_ChannelXErrorSimpleMIM():
    worker = Worker()
    await worker.run(
        config_name="ChannelXErrorSimpleMIM",
        ned_file_path="simulations/simulation_test.ini",
    )
    print(worker.output)
    worker.print_results()
    # MIM: both sides emit a photon and both channels independently apply X
    # at rate 0.1, so the memory ends up with an X error in the asymmetric
    # cases (~2·0.1·0.9 = 0.18). Symmetric X cancels out at the BSA.
    assert worker.results["EndNode1<-->EndNode2"]["data"] == {
        "Fidelity": 0.816393,
        "Xerror": 0.183607,
        "Zerror": -0.00195065,
        "Yerror": 0.00195065,
    }
    assert worker.results["EndNode2<-->EndNode1"]["data"] == {
        "Fidelity": 0.816393,
        "Xerror": 0.183607,
        "Zerror": -0.00195065,
        "Yerror": 0.00195065,
    }


@pytest.mark.asyncio
async def test_ChannelXErrorSimpleMM():
    worker = Worker()
    await worker.run(
        config_name="ChannelXErrorSimpleMM",
        ned_file_path="simulations/simulation_test.ini",
    )
    print(worker.output)
    worker.print_results()
    # MM: only one photon traverses the channel (sender → receiver's qnic_r),
    # so the X error fires at rate 0.1 ≈ memory X error rate.
    assert worker.results["EndNode1<-->EndNode2"]["data"] == {
        "Fidelity": 0.911253,
        "Xerror": 0.0887475,
        "Zerror": -0.00348995,
        "Yerror": 0.00348995,
    }
    assert worker.results["EndNode2<-->EndNode1"]["data"] == {
        "Fidelity": 0.911253,
        "Xerror": 0.0887475,
        "Zerror": -0.00348995,
        "Yerror": 0.00348995,
    }

@pytest.mark.asyncio
async def test_ChannelXErrorSimpleMSM():
    worker = Worker()
    await worker.run(
        config_name="ChannelXErrorSimpleMSM",
        ned_file_path="simulations/simulation_test.ini",
    )
    print(worker.output)
    worker.print_results()
    assert worker.results["EndNode1<-->EndNode2"]["data"] == {
        "Fidelity": 0.822686,
        "Xerror": 0.177314,
        "Zerror": -0.00245087,
        "Yerror": 0.00245087,
    }
    assert worker.results["EndNode2<-->EndNode1"]["data"] == {
        "Fidelity": 0.822686,
        "Xerror": 0.177314,
        "Zerror": -0.00245087,
        "Yerror": 0.00245087,
    }

@pytest.mark.asyncio
async def test_MIM_Werner_State_Channel():
    worker = Worker()
    await worker.run(
        config_name="Channel_Error_Werner_State_MIM",
        ned_file_path="simulations/simulation_test.ini",
    )
    print(worker.output)
    worker.print_results()
    assert worker.results["EndNode1<-->EndNode2"]["data"] == {
        "Fidelity": 0.495203,
        "Xerror": 0.224063,
        "Zerror": 0.211378,
        "Yerror": 0.0693559,
    }
    assert worker.results["EndNode2<-->EndNode1"]["data"] == {
        "Fidelity": 0.495203,
        "Xerror": 0.224063,
        "Zerror": 0.211378,
        "Yerror": 0.0693559,
    }


@pytest.mark.asyncio
async def test_MM_Werner_State_Channel():
    worker = Worker()
    await worker.run(
        config_name="Channel_Error_Werner_State_MM",
        ned_file_path="simulations/simulation_test.ini",
    )
    print(worker.output)
    worker.print_results()
    assert worker.results["EndNode1<-->EndNode2"]["data"] == {
        "Fidelity": 0.661858,
        "Xerror": 0.15364,
        "Zerror": 0.152754,
        "Yerror": 0.0317478,
    }
    assert worker.results["EndNode2<-->EndNode1"]["data"] == {
        "Fidelity": 0.661858,
        "Xerror": 0.15364,
        "Zerror": 0.152754,
        "Yerror": 0.0317478,
    }

@pytest.mark.asyncio
async def test_MSM_Werner_State_Channel():
    worker = Worker()
    await worker.run(
        config_name="Channel_Error_Werner_State_MSM",
        ned_file_path="simulations/simulation_test.ini",
    )
    print(worker.output)
    worker.print_results()
    assert worker.results["EndNode1<-->EndNode2"]["data"] == {
        "Fidelity": 0.497312,
        "Xerror": 0.215188,
        "Zerror": 0.194648,
        "Yerror": 0.0928518,
    }
    assert worker.results["EndNode2<-->EndNode1"]["data"] == {
        "Fidelity": 0.497312,
        "Xerror": 0.215188,
        "Zerror": 0.194648,
        "Yerror": 0.0928518,
    }
