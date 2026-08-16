# 外部AI敵対レビュー記録（強化コードの再レビュー・round2）

- **日付**：2026-08-15
- **対象**：external_review_gate 強化（[A]--baselineグランドファーザリング廃止 [B]validate_record内容/gpg署名検査）
- **レビュアー（両最上位・ユーザー指示）**：ChatGPT **GPT-5.6 Sol(高)** ／ Google **Gemini 3.1 Pro 拡張**
- **判定：両モデルとも再び NO-GO（3回連続で収束）**

## 収束した結論＝ローカルの自己参照ゲートは原理的に「強制」になり得ない
- **自己参照パラドックス（両者・致命的）**：ゲートのコード冒頭に `return True`（またはvalidate()をreturn True化／自身を対象から除外）を挿入すれば、**ハッシュ検証に到達する前に常にGOを返す**。「gate自身を編集したらFAILした」実証は"善良なgateが実行されている時だけ"の証明。measurement code == measured code は trust root にならない。→ **gate自身のSHAをgate外(immutableなCI policy)で確認しない限り解消不能**。
- **[A]の残バイパス**：①**rename**（対象をリネーム＋import修正→"新規ファイル"扱い→--baseline→WARN→出荷）②**registry(external_reviews.json)直編集**（baseline/hashを改変後値に一致させれば"変更なし"と誤認）。＝私が[C]で残穴と認めたregistry可変性で[A]は骨抜き。
- **署名のダウングレード攻撃（両者・致命的）**：`TRUST_PUBKEY存在時だけ署名必須`＝**鍵ファイルを削除/renameするだけで署名検証をスキップ**して内容検査のみへ降格。＋`gpg --verify`は鍵の信頼未設定でもrc0（攻撃者が自分の鍵で署名しTRUST_PUBKEYを上書きすれば偽署名が受理）。＋**`--keyring`にarmored .asc直指定はGnuPG版依存で恒久的に検証失敗する回帰リスク**（要dearmor/keybox）。

## 見つかった実バグ（ローカル層でも要修正）
- **`validate_record`のverdict語検査が両方向に壊れている**：
  - 偽陰性＝`\bGO\b`は日本語隣接/全角ＧＯ/「GOGO」「GO/NO-GO」に脆い。
  - **偽陽性（回帰）＝実際のAIレビューは「NO-GOの条件には合致しないため判定はGO」と書く→"NO-GO語がある"で正規の合格を誤ってFAILさせる**。＝この文字列grep方式自体が不適切。
- **TOCTOU**：open/hash/useが複数openで途中差替え可能→一度bytesを読み、その同一bytesにhash/内容/署名検証を行う設計にすべき。
- **status未分離**：`review invalid`と`verifier infrastructure broken`は別statusにすべき。

## 正しい設計（GPT提案・CI phaseで採用）
- verdictを本文grepで判定しない。**署名された構造化manifest**（target_sha256 / target_path / verdict / model・provider / review_timestamp / review_record_sha256）を作り、**manifest自体を署名対象**にする。境界が明確になる。
- この署名manifestを**GitHub Actions(ローカル外・immutable)が検証**し、**gate自身のSHAもCI policy側で確認**、ブランチ保護で必須化。＝ここで初めて自己参照とregistry可変性が解ける。

## 帰結（意思決定）
- **ローカルでGO登録はしない**（3回NO-GO・原理的に不可）。ローカルgateは「事故・怠慢・うっかりスキップを減らす＋債務を毎セッション表出する衛生層」と位置づける。
- **真の強制＝CI phase**（署名manifest＋immutable CI policy＋ブランチ保護）に一本化。文字列grep式のvalidate_recordは廃し、署名manifestへ置換する（次段階）。
