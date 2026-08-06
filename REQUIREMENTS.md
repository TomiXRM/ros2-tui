# ros2-tui 要件定義

ROS 2 (Jazzy) の action 操作を中心とした TUI クライアント。
`ros2 action send_goal` の YAML 手打ち地獄をフォーム入力に置き換える。

## 解決したい課題

`ros2 action send_goal` の CLI 体験:

- action 名 → 型名 → YAML 引数、と 3 段階のタイピング/タブ補完が必要
- タブ補完で展開された YAML は複数行になり、カーソル移動が苦痛
- `key: value` のコロン後スペース、カンマ後スペースなど YAML 構文の罠が多い
- フィールドの型が見えないので、何を入れればいいか毎回型定義を調べる

## スコープ(Tier)

### Tier 1(MVP)

| 機能 | 内容 |
|---|---|
| action 一覧 | 起動中の action server を一覧表示、選択可能 |
| フォーム入力 | Goal 型を introspection してフィールドごとに入力欄を自動生成。**各欄の横に型名を表示**(`float32`, `string`, `geometry_msgs/Pose` 等) |
| send_goal | フォームの値から Goal message を組み立てて送信 |
| feedback 監視 | 送信後、feedback / status / result をリアルタイム表示 |
| cancel | 実行中 goal のキャンセル |

### Tier 2

- param 一覧・get(ノード選択 → param 一覧 → 値表示)
- param set(型付きフォームで入力)

### Tier 3

- topic pub(型 introspection → フォーム → publish。連続 pub / rate 指定)

### 非スコープ(当面やらない)

- topic echo / node graph 表示(lazyros の領分。必要になったら追加)
- service call(仕組みは action と同じなので後から安く追加できる)
- launch / bag 操作

## UI 設計

フレームワーク: **Textual**(Python 製 TUI の事実上の標準。フォーム widget、
リアクティブ更新、mac/Linux 両対応)

### 画面構成(3 ペイン + フォーム)

```
┌─ Actions ──────────────┬─ Goal Form ──────────────────────┐
│ /fibonacci             │ order        [10        ] int32  │
│ /navigate_to_pose      │                                  │
│ /dock                  │ ── nested: pose (Pose) ──────────│
│                        │ position.x   [0.0       ] float64│
│ (/ でフィルタ)          │ position.y   [0.0       ] float64│
│                        │                                  │
│                        │ [Send Goal]  [Cancel]            │
├────────────────────────┴──────────────────────────────────┤
│ Feedback / Result                                         │
│ 12:00:01 feedback: {partial_sequence: [0,1,1,2]}          │
│ 12:00:03 result:   {sequence: [0,1,1,2,3,5]} SUCCEEDED    │
└───────────────────────────────────────────────────────────┘
```

- 左: action リスト(選択で右にフォーム生成)。Tier 2/3 はタブ切替
  (`a`ction / `p`aram / `t`opic)で同じレイアウトを使い回す
- 右上: **型 introspection から自動生成されるフォーム**
  - ネストした message はフラット展開(`pose.position.x` 形式)+ 見出し
  - Tab / Shift+Tab でフィールド移動(CLI の「左キー連打」の解消)
  - デフォルト値は型定義の default をプリセット
- 下: feedback / result のログ。goal status(ACCEPTED/EXECUTING/SUCCEEDED…)を色分け

### フォーム形式について(代替案の検討)

- 採用: **フィールドごとの入力欄 + 型ラベル**(要望どおり)
- 配列 / 可変長フィールド: まずは 1 行テキストで `[1, 2, 3]` 形式入力
  (ネスト配列のフォーム化は複雑すぎるので初期は YAML fallback)
- 代替案として「編集可能な YAML バッファを $EDITOR で開く」も考えたが、
  型が見えない・TUI から離れる、で本末転倒なので不採用
- 入力履歴: 同じ action への前回入力値を保持(再送が一番多いユースケース)

## アーキテクチャ

```
textual (UI) ─── rclpy (通信) ─── rosidl introspection (フォーム生成)
```

- `rclpy.action.ActionClient` で send_goal / feedback / cancel(ros2cli の
  `ros2action` パッケージと同じ経路。CLI をサブプロセスで叩かない)
- action 発見: `ros2action.api.get_action_names_and_types()` 相当の graph API
- フォーム生成: `get_action(type).Goal().get_fields_and_field_types()` を再帰
- 値の設定: `rosidl_runtime_py.set_message_fields()`
### 非同期設計

- **asyncio-for-robotics (afor) に依存する**(pure には組まない)
  - 上流 https://github.com/2lian/asyncio-for-robotics は PyPI にあるが
    action 対応は未マージ(PR #16, `TomiXRM:feat/ros2-action-support`)。
    強化版 action 対応(handle 即返し + feedback subscriber +
    ActionRejected / ActionResultUnknown + call() タイムアウト)は
    フォーク https://github.com/TomiXRM/asyncio-for-robotics の main に
    マージ済み(PR #3)。pixi の pypi-dependencies でフォーク main に
    git 依存し、上流マージ後に PyPI 依存へ差し替える
  - ThreadedSession が rclpy spin を別スレッドで回し、action の
    send_goal / feedback / result / cancel を asyncio で await できる。
    Textual は asyncio アプリなのでそのまま統合できる
  - afor が Jazzy/pixi で問題を起こした箇所だけ pure なグルーに差し替える
- **リスト更新(action / node / topic)**:
  - 手動更新(`r` キー)+ 数秒間隔の自動更新(`set_interval`、間隔は定数)
  - graph query はブロックしうるので Textual の `run_worker(thread=True)` で
    実行し、結果だけ UI スレッドに返す(タイピングを止めない)
  - 自動更新は選択中の項目とフォーム入力を保持したまま差分反映

## 環境・配布

- **pixi + RoboStack** で ROS 2 Jazzy を conda パッケージとして導入
  (システムの ROS / pip の ROS に依存しない。lazyros との差別化ポイント)
- channels: `conda-forge`, `robostack-jazzy`
- platforms: `osx-arm64`, `linux-64`(pixi.toml に追記)
- 依存: `ros-jazzy-ros-base`(または必要最小の rclpy + rosidl 系)+ `textual`
- `pixi run ros2-tui` で起動。動作確認用に `ros-jazzy-example-interfaces`
  の fibonacci action server をタスクとして用意

## 動作確認シナリオ(受け入れ条件)

1. `pixi run demo-server`(fibonacci action server 起動)
2. `pixi run ros2-tui` → `/fibonacci` がリストに出る
3. 選択 → `order [   ] int32` のフォームが出る
4. 10 を入れて Send → feedback がストリーム表示され、result が SUCCEEDED
5. 上記が mac (osx-arm64) と Ubuntu (linux-64) の両方で通る
