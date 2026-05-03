# シミュレーションテストスイート

> **English version**: see [README.md](README.md).

これらのシミュレーションテストは複数のシミュレーションシナリオを実行し、忠実度などの結果を確認することで、シミュレータが期待通りに動作するかを確認します。シミュレーションテストスイートは pytest 上に xdist と asyncio プラグインで構築されており、複数のシミュレーションを並列に実行できます。

## 使い方

```sh
$ cd simulation_tests

# 依存をインストール
$ pip install -r ../requirements.txt

# すべてのテストを 1 プロセスで実行
$ pytest

# すべてのテストを並列実行
$ pytest -n auto

# 4 コアで実行
$ pytest -n 4

# デバッグ用に stdout を表示しながら 1 プロセスで実行。
# `print()` でデバッグ用の出力を確認できる。
$ pytest -s

# "NoErrorMIM" テストのみ実行
$ pytest -s -k NoErrorMIM

```

## 新しいテストケースの追加

pytest に検出されるよう、テストファイル名は `test_` で始める必要があります。

```python
from .utils import Worker
import pytest


# シミュレーション実行を "await" で待つので async 関数にする
@pytest.mark.asyncio
async def test_NoErrorMIM():  # 関数名は "test_" で始める必要がある
    # worker はシミュレータとシミュレーション結果を管理する
    worker = Worker()
    await worker.run(
        # 指定 ini ファイル内の config 名
        config_name="NoErrorMIM",
        # quisp バイナリの位置からの相対パス
        ned_file_path="simulations/simulation_test.ini"
    )
    # `pytest -s` 実行時にすべてのシミュレータ出力を表示する
    print(worker.output)
    worker.print_results()

    # シミュレーション結果が一致するかを確認
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
```
