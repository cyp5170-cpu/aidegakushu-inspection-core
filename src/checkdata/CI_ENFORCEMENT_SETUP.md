# CI phase セットアップ手順（真の外部レビュー強制＝ローカル外の信頼基点）

3回の敵対レビュー(GPT-5.6 Sol / Gemini 3.1 Pro拡張)の確定結論＝**ローカルの自己参照ゲートは強制不可**。
真の強制＝**GitHub Actions(改ざん不能)＋ブランチ保護＋署名manifest**。以下はユーザー(=秘密鍵の保持者＝トラストアンカー)が行う手順。

> 役割：**Claudeは署名しない/秘密鍵に触れない**。Claudeは検証コード(gate/workflow)を書き、あなたが「レビューを実施し、承認物に署名」する。

## 前提（このリポジトリで実装済み・Claude作成）
- `src/external_review_gate.py --gen-manifest` … 署名対象の構造化manifest(`src/checkdata/external_reviews_manifest.json`)を生成（全critical fileのsha256＋verdict）。
- `.github/workflows/external-review.yml` … CIの検証本体（署名検証＋各fileのsha一致＋verdict=GOを必須化。**gate自身のshaも含む**ので改ざんはCIで露見）。検証はYAML内インライン＝別スクリプト改ざん不可。

## 手順
### 1) gpg鍵を作る（秘密鍵はあなたのPCだけに保持）
```
gpg --full-generate-key            # 種類=ECC(ed25519)推奨、氏名/メール入力
gpg --fingerprint                  # 40桁の指紋を控える（例: ABCD 1234 ...）
gpg --armor --export <あなたのメール> > src/checkdata/trusted_reviewers.asc   # 公開鍵をrepoへ
```

### 2) ワークフローに指紋をピン留め（鍵すり替え防止の要）
`.github/workflows/external-review.yml` の `EXPECTED_FINGERPRINT:` を、1)の40桁指紋（空白除去）に書き換える。
＝公開鍵ファイルを攻撃者が上書きしても、この指紋(ブランチ保護対象のYAMLに固定)と不一致で弾く。

### 3) 各critical fileを外部レビュー→register→manifest生成→署名
検品コア10ファイルを順に外部AI(OpenAI+Gemini)で敵対レビューし、GOのものを登録：
```
py src/external_review_gate.py --register --file src/xxx.py --verdict GO \
    --model "GPT-5.6 Sol / Gemini 3.1 Pro" --record src/checkdata/external_reviews/xxx.md
py src/external_review_gate.py --gen-manifest                       # GO反映のmanifestを再生成
gpg --armor --detach-sign src/checkdata/external_reviews_manifest.json   # → .asc 署名を作る（秘密鍵で）
```
※現状GO=0（3回NO-GOのため）。まず各fileを実際にレビューしてGOにしないと、CIは全ファイルをブロックする（＝正しい）。

### 4) プライベートGitHubリポジトリを作成しpush（src/のみ・.gitignoreで医療コンテンツ除外済）
```
# gh未導入。GitHub Web か GitHub Desktop で「新規プライベートリポジトリ」を作成し、リモートを設定：
git branch -M main
git remote add origin https://github.com/<あなた>/<repo>.git
git push -u origin main
```
※`.gitignore`で追跡対象は`src/`と`.github/`のみ（episodes/音声/画像/台本/大容量は除外＝確認済み）。

### 5) ブランチ保護＋必須チェック（ここで"強制"が成立）
GitHub → Settings → Branches → Add rule（main）：
- **Require a pull request before merging**（直push禁止）
- **Require status checks to pass** → `external-review-gate / verify` を必須に
- （可能なら）Include administrators / 署名コミット必須

→ これで「検品コアを外部レビュー(署名manifest)なしに変更したPRは、CIがsha不一致/非GOでfail＝merge不可」。
   gate自身に`return True`を挿入してもshaが変わり署名manifestと不一致→CIでブロック（自己参照パラドックスをローカル外で解決）。

## 残る前提（正直に）
- **秘密鍵の保護はあなたの責任**（鍵が漏れれば偽署名可能＝トラストアンカーは人）。
- ローカルでの直編集は依然可能だが、**mainへmergeするにはCIを通る必要がある**＝公開/共有される成果物は強制下に入る。
- workflow/manifest生成コードもcriticalに含め、変更時は同じ強制を受ける（自己適用）。
