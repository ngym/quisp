# quisp::utils

> **English version**: see [README.md](README.md).

## ComponentProvider

`ComponentProvider` は quisp のモジュール内部で使われるクラスです。
このクラスは quisp のモジュールから他のモジュールへアクセスする手段を提供します。
このクラスは [Strategy Pattern](https://en.wikipedia.org/wiki/Strategy_pattern) を採用しています。
`ComponentProvider` 自身は他のモジュールの取得方法を知りません。実際の挙動は `IComponentProviderStrategy` を継承するクラスで定義されます。

## 単体テスト

`IComponentProviderStrategy` を継承するクラスを作成することで、`ComponentProvider` から返されるモジュールを差し替えられます。
OMNeT++ のアーキテクチャは強力ですが、その分単体テストを書きにくいです。この仕組みはその問題を解決します。
