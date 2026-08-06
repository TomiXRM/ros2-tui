# ros2-tui

ROS 2 (Jazzy) の action / topic / service / param を TUI で操作するクライアント。
`ros2 action send_goal` の YAML 手打ちの代わりに、型 introspection で自動生成された
フォームに値を入れて送信できます。

## セットアップ

[pixi](https://pixi.sh) だけあれば動きます(システムに ROS 不要。RoboStack の
conda パッケージで ROS 2 Jazzy ごと入ります。mac / Ubuntu 対応)。

```sh
curl -fsSL https://pixi.sh/install.sh | sh   # pixi 未導入なら
git clone https://github.com/TomiXRM/ros2-tui.git
cd ros2-tui
pixi install --locked
```

## 使い方

```sh
pixi run ros2-tui
```

- 上部タブで機能を切り替え: **Topic / Service / Action / Set Param / Get Param**
- 左ペイン: 起動中のエンティティ一覧(3 秒ごと自動更新、`r` で手動更新)
- 右ペイン: 選択したものの入力フォーム。各欄の右に型が表示されます。
  値は YAML として解釈されるので `42` / `3.14` / `true` / `[1, 2, 3]` がそのまま書けます。
  空欄はデフォルト値のままになります
- 下ペイン: feedback / result / レスポンスのログ

| タブ | できること |
|---|---|
| Action | goal をフォーム入力して Send Goal、feedback をリアルタイム表示、Cancel |
| Topic | メッセージをフォーム入力して Publish |
| Service | リクエストをフォーム入力して Call、レスポンス表示 |
| Set Param | ノードのパラメータ一覧を編集して Apply(変更分だけ set) |
| Get Param | ノードのパラメータの名前・値・型を表示 |

### 動作確認(デモ)

別ターミナルで fibonacci action サーバを起動して試せます:

```sh
pixi run demo-server
```

Action タブに `/fibonacci` が出るので、選択して `order` に `10` → Send Goal。

### テスト

```sh
pixi run test
```

## 既存の ROS 環境と通信する場合

環境は CycloneDDS(`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`)で動きます。
他のノードと通信できないときは、相手側と `ROS_DOMAIN_ID` / RMW / QoS が
揃っているか確認してください。
