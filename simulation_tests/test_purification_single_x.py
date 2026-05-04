from .utils import Worker
import pytest


@pytest.mark.asyncio
async def test_Single_X_Purification_MIM_No_Error():
    worker = Worker()
    await worker.run(
        config_name="Single_X_Purification_MIM_No_Error",
        ned_file_path="simulations/simulation_test.ini",
    )
    print(worker.output)
    worker.print_results()
    assert worker.results["EndNode1<-->EndNode2"]["data"] == {
        "Fidelity": 1.0,
        "Xerror": 0.0,
        "Zerror": 0.0,
        "Yerror": 0.0,
    }
    assert worker.results["EndNode2<-->EndNode1"]["data"] == {
        "Fidelity": 1.0,
        "Xerror": 0.0,
        "Zerror": 0.0,
        "Yerror": 0.0,
    }


@pytest.mark.asyncio
async def test_Single_X_Purification_MM_No_Error():
    worker = Worker()
    await worker.run(
        config_name="Single_X_Purification_MM_No_Error",
        ned_file_path="simulations/simulation_test.ini",
    )
    print(worker.output)
    worker.print_results()
    assert worker.results["EndNode1<-->EndNode2"]["data"] == {
        "Fidelity": 1.0,
        "Xerror": 0.0,
        "Zerror": 0.0,
        "Yerror": 0.0,
    }
    assert worker.results["EndNode2<-->EndNode1"]["data"] == {
        "Fidelity": 1.0,
        "Xerror": 0.0,
        "Zerror": 0.0,
        "Yerror": 0.0,
    }

@pytest.mark.asyncio
async def test_Single_X_Purification_MSM_No_Error():
    worker = Worker()
    await worker.run(
        config_name="Single_X_Purification_MSM_No_Error",
        ned_file_path="simulations/simulation_test.ini",
    )
    print(worker.output)
    worker.print_results()
    assert worker.results["EndNode1<-->EndNode2"]["data"] == {
        "Fidelity": 1.0,
        "Xerror": 0.0,
        "Zerror": 0.0,
        "Yerror": 0.0,
    }
    assert worker.results["EndNode2<-->EndNode1"]["data"] == {
        "Fidelity": 1.0,
        "Xerror": 0.0,
        "Zerror": 0.0,
        "Yerror": 0.0,
    }


@pytest.mark.asyncio
async def test_Single_X_Purification_MIM_Werner_State():
    worker = Worker()
    await worker.run(
        config_name="Single_X_Purification_MIM_Werner_State",
        ned_file_path="simulations/simulation_test.ini",
    )
    print(worker.output)
    worker.print_results()
    assert worker.results["EndNode1<-->EndNode2"]["data"] == {
        "Fidelity": 0.501218,
        "Xerror": 0.0919581,
        "Zerror": 0.338388,
        "Yerror": 0.0684362,
    }
    assert worker.results["EndNode2<-->EndNode1"]["data"] == {
        "Fidelity": 0.501218,
        "Xerror": 0.0919581,
        "Zerror": 0.338388,
        "Yerror": 0.0684362,
    }


@pytest.mark.asyncio
async def test_Single_X_Purification_MM_Werner_State():
    worker = Worker()
    await worker.run(
        config_name="Single_X_Purification_MM_Werner_State",
        ned_file_path="simulations/simulation_test.ini",
    )
    print(worker.output)
    worker.print_results()
    assert worker.results["EndNode1<-->EndNode2"]["data"] == {
        "Fidelity": 0.661579,
        "Xerror": 0.0276459,
        "Zerror": 0.292033,
        "Yerror": 0.0187412,
    }
    assert worker.results["EndNode2<-->EndNode1"]["data"] == {
        "Fidelity": 0.661579,
        "Xerror": 0.0276459,
        "Zerror": 0.292033,
        "Yerror": 0.0187412,
    }

@pytest.mark.asyncio
async def test_Single_X_Purification_MSM_Werner_State():
    worker = Worker()
    await worker.run(
        config_name="Single_X_Purification_MSM_Werner_State",
        ned_file_path="simulations/simulation_test.ini",
    )
    print(worker.output)
    worker.print_results()
    assert worker.results["EndNode1<-->EndNode2"]["data"] == {
        "Fidelity": 0.497072,
        "Xerror": 0.0778157,
        "Zerror": 0.348077,
        "Yerror": 0.077035,
    }
    assert worker.results["EndNode2<-->EndNode1"]["data"] == {
        "Fidelity": 0.497072,
        "Xerror": 0.0778157,
        "Zerror": 0.348077,
        "Yerror": 0.077035,
    }
