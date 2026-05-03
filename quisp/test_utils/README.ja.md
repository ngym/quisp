# テストユーティリティ

> **English version**: see [README.md](README.md).

## 使い方

`TestUtils.h` を使い、テストファイル中で `using namespace quisp_test` を宣言します。

最初にテスト中で `prepareSimulation` を呼び出してください。これは現在のシミュレーションがあれば破棄し、新しいシミュレーションを生成します。

テスト対象のコンポーネントに値を設定したいときは `setPar~` 系の関数を使います。
テストネットワークの構築が終わったら `TestSimulation::run` を呼び出すことで、テストネットワーク上でシミュレーションが走ります。1 ステップずつ進めたい場合は `TestSimulation::executeNextEvent` を呼び出します。

QRSA モジュールのテストを書く場合、QRSA モジュールは QNode に依存しているため、QNode コンポーネントが必要です。

## パケットの取得

テスト対象モジュールからパケットを取り出すには `TestGate` を使います。
`TestGate` は `messages` メンバを持ち、ゲートが `cMessage` を受信するとそのメッセージをコピーして `messages` フィールドに格納します。
シミュレーション実行後に `TestGate` の `messages` フィールドを取得できます。

## 例

```cpp
using namespace quisp_test;

namespace {

// AppTestTarget で ComponentProvider 経由のコンポーネント提供に使う Strategy
class Strategy : public quisp_test::TestComponentProviderStrategy {
 public:
  Strategy(TestQNode *_qnode) : parent_qnode(_qnode) {}
  cModule *getQNode() override { return parent_qnode; }

 private:
  TestQNode *parent_qnode;
};

class AppTestTarget : public quisp::modules::Application {
 public:
  using quisp::modules::Application::getParentModule;
  using quisp::modules::Application::initialize;
  using quisp::modules::Application::par;
  explicit AppTestTarget(TestQNode *parent_qnode)
    : Application(),
      toRouterGate(new TestGate(this, "toRouter")) {
    // provider に Strategy をセット。これでこのモジュールから Strategy 経由で他コンポーネントを使える。
    this->provider.setStrategy(std::make_unique<Strategy>(parent_qnode));
    // simulation はこのモジュールの ComponentType 情報を必要とする
    setComponentType(new TestModuleType("test qnode"));
  }

  // メンバ値を確認するためのユーティリティメソッド
  std::vector<int> getOtherEndNodeAdresses() { return this->other_end_node_addresses; }
  int getAddress() { return this->my_address; }

  // このモジュールで使うゲート。単体テストでは ned ファイルが無いので注入する必要がある。
  TestGate *toRouterGate;

  // `gate` メソッドのオーバーライド
  cGate *gate(const char *gatename, int index = -1) override { return toRouterGate; };
};

TEST(AppTest, Init_OneConnection_Sender) {
  // 最初に simulation をセットアップ
  auto *sim = prepareSimulation();

  // address 123 を持つ qnode を作成
  auto *mock_qnode = new TestQNode{123};

  // テスト対象モジュール（quisp::module::Application を継承する実テスト対象）を作成
  auto *app = new AppTestTarget{mock_qnode};

  // モジュールへパラメータを設定
  setParBool(app, "EndToEndConnection", true);
  setParInt(app, "NumberOfResources", 5);
  setParInt(app, "num_measure", 1);
  setParInt(app, "TrafficPattern", 1);
  setParInt(app, "LoneInitiatorAddress", mock_qnode->address);

  // app を現在の simulation に登録
  sim->registerComponent(app);

  auto *mock_qnode2 = new TestQNode{456};

  // cModule::callInitialize 経由で Application::initialize を呼ぶ。
  // cModule::callInitialize は Application::initialize 呼び出し前にコンテキスト等を準備する。
  app->callInitialize();

  // app の address が正しく初期化されていることを確認
  ASSERT_EQ(app->getAddress(), mock_qnode->address);
  // app の他のアドレスを確認
  ASSERT_EQ(app->getOtherEndNodeAdresses().size(), 1);

  // テスト simulation を実行。パケット転送等のイベントが処理される。
  sim->run();

  // app が "toRouter" ゲートに 1 件メッセージを送ったことを確認
  ASSERT_EQ(app->toRouterGate->messages.size(), 1);

  // TestGate には app モジュールから受信したメッセージが入っている。
  // 最初のメッセージを取り出す。
  auto *msg = app->toRouterGate->messages.at(0);
  ASSERT_NE(msg, nullptr);

  // msg の型は cMessage* なので ConnectionSetupRequest* にキャスト
  auto *pkt = dynamic_cast<ConnectionSetupRequest *>(msg);
  // app から送られた ConnectionSetupRequest の詳細を確認
  ASSERT_EQ(pkt->getActual_srcAddr(), 123);
  ASSERT_EQ(pkt->getActual_destAddr(), mock_qnode2->address);
  ASSERT_EQ(pkt->getSrcAddr(), 123);
  ASSERT_EQ(pkt->getDestAddr(), 123);
  ASSERT_EQ(pkt->getNumber_of_required_Bellpairs(), 5);
}
}
```
