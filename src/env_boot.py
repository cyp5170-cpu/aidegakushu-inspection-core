# -*- coding: utf-8 -*-
"""env_boot: Windows「setx反映漏れ」対策（読取専用・per-key最小設計・Claude専有）。

背景：`setx` はレジストリ(HKCU\\Environment=ユーザー環境変数)に書くが、その値を読むのは
"setx実行後に環境を読み直した親から起動された新規プロセス" だけ。setx以前から開いていた
ターミナルを親に起動し直すと古い環境を引き継ぎ、有効なキーでも「未設定」に見える（実害確認済）。

■ 設計（外部AI敵対レビュー GPT-5.6 Sol round1〜6 を反映した最小設計）
  必要な1キーだけを都度 `RegQueryValueEx` で読む（per-key）：
    ・値名の大小文字は Windows API が case-insensitive に吸収（自前dict比較なし）。
    ・列挙しない＝列挙TOCTOUなし。
    ・**REG_SZ のみ許可**。REG_EXPAND_SZ は「%VAR% が"古いプロセス環境"で展開され、まさに本モジュールが
      直したい stale 環境へ戻る（OLD値/未展開%NAMEを正常値化）」矛盾があるため **禁止(error)**（round6）。
      ＝APIキー類は素の文字列で十分。展開が要るパス系は素の絶対パスで setx すること。
  **os.environ は一切変更しない**（read-only）。値は resolve()/resolve_ex() で取り、SDK へ api_key= 等で明示渡し。
  エラーは戻り値(resolve_ex)か例外(resolve=fail-closed・round6)で必ず表出＝サイレントに死なせない。

  正直な限界（不可避・文書化）：os.environ とレジストリを"外部の並行変更に対して原子的に跨いで"読む手段は
  OSに無い。単一スレッドimport時前提の best-effort（実行中の外部並行変更は人＝トラストアンカーのバックストップ）。

方針（ユーザー恒久ルール）＝「記憶や手順に頼らず機械で担保／APIをサイレントに死なせない」。
※秘密の値そのものはこのファイルに持たない（キー"名"のみ）。
"""
from __future__ import annotations
import os

# フォールバック対象のキー"名"（検品/生成系が参照しうるもの。値は持たない）。
KEYS = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
    "MEDISEARCH_API_KEY",
    "OPENAI_API_KEY", "OPENAI_MODEL",
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_MODEL",
    "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "NCBI_EMAIL",
)

# winreg 型定数（winreg 未import環境でも参照できるよう保持。実winregの値と一致）
_REG_SZ = 1
_REG_EXPAND_SZ = 2


class EnvBootError(RuntimeError):
    """resolve() の fail-closed 用。インフラ異常（アクセス障害・型不正等）を握りつぶさず送出する。"""


def _classify(val, typ):
    """レジストリの (value, type) を検証。(value, error)。
    REG_SZ の文字列のみ許可。REG_EXPAND_SZ は禁止(stale展開矛盾・round6)。他型も禁止(#4)。"""
    if typ == _REG_SZ:
        if isinstance(val, str):
            return val, None
        return None, f"non-str-type:{typ}"
    if typ == _REG_EXPAND_SZ:
        return None, "reg-expand-unsupported"   # %VAR%は古いプロセス環境で展開され得る＝目的と矛盾
    return None, f"unsupported-type:{typ}"


def _query_registry(name, _winreg=None):
    """HKCU\\Environment から name を1件だけ読む。(value, error)。
    キー/値の不在は「正常な補完元なし」＝(None, None)。アクセス障害・型不正のみ error(#3)。
    _winreg はテスト専用の注入口（本番は None＝実 winreg）。"""
    wr = _winreg
    if wr is None:
        if os.name != "nt":
            return None, None                    # Windows以外は安全な no-op
        try:
            import winreg as wr
        except Exception as e:
            return None, f"winreg-import:{type(e).__name__}"
    try:
        with wr.OpenKey(wr.HKEY_CURRENT_USER, "Environment") as k:
            try:
                val, typ = wr.QueryValueEx(k, name)   # case-insensitive lookup
            except FileNotFoundError:
                return None, None                # その値が無い＝正常な未設定
            except OSError as e:
                return None, f"query:{type(e).__name__}"
    except FileNotFoundError:
        return None, None                        # Environmentキー自体が無い＝正常
    except OSError as e:
        return None, f"openkey:{type(e).__name__}"
    return _classify(val, typ)


def resolve_ex(name, _environ=None, _query=None):
    """name の実効値と解決時のインフラ異常を返す：(value, error)。**副作用なし・os.environ不変**。
    os.environ 優先（空文字""も"設定済み"として尊重・#1／Windowsのos.environは値名case-insensitive）。
    無ければレジストリを per-key で1件読む。error はアクセス障害・型不正等の異常のみ（#3観測）。
    _environ/_query はテスト専用の注入口（本番では None）。"""
    environ = os.environ if _environ is None else _environ
    query = _query_registry if _query is None else _query
    if name in environ:                          # 空文字も"設定済み"＝尊重(#1)
        return environ[name], None
    return query(name)


def resolve(name):
    """name の実効値を返す（**fail-closed**・round6）。インフラ異常は例外送出＝サイレントに死なせない。
    None を返すのは「本当にどこにも無い」場合だけ。エラーを黙って握りたくない設計。"""
    value, error = resolve_ex(name)
    if error is not None:
        raise EnvBootError(f"{name}: {error}")
    return value


def sweep(names=KEYS):
    """診断用：names の解決状況を per-key で読み、副作用なしで返す（注入しない）。
    ※各キーは独立に読む（レジストリ/環境は外部並行変更され得るため"跨る原子スナップショット"は主張しない＝不可避の限界）。
    {"env":[...], "registry":[...], "missing":[...], "errors":[(name,reason)]}"""
    env, registry, missing, errors = [], [], [], []
    for name in names:
        if name in os.environ:
            env.append(name); continue
        val, err = _query_registry(name)
        if err:
            errors.append((name, err))
        elif val is not None:
            registry.append(name)
        else:
            missing.append(name)
    return {"env": env, "registry": registry, "missing": missing, "errors": errors}


def _fake_winreg(*, open_exc=None, query_exc=None, query_result=None):
    """self-test 用の疑似 winreg（実レジストリを触らず _query_registry の境界を検査する）。"""
    class _K:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _W:
        HKEY_CURRENT_USER = 0
        REG_SZ = _REG_SZ
        REG_EXPAND_SZ = _REG_EXPAND_SZ

        def OpenKey(self, root, sub):
            if open_exc:
                raise open_exc
            return _K()

        def QueryValueEx(self, k, name):
            if query_exc:
                raise query_exc
            return query_result

    return _W()


def _selftest():
    """契約の回帰テスト。**実 os.environ / 実レジストリを一切触らず**（注入式で）決定論検査。
    機械判定語は ASCII（encoding非依存）。round6：_classify と _query_registry の境界を直接テスト＋副作用ゼロを検証。"""
    ok, msgs = True, []

    def fail(m):
        nonlocal ok
        ok = False
        msgs.append(m)

    env_before = dict(os.environ)                # 副作用ゼロを実測（round6/MEDIUM）
    q = lambda table: (lambda name: table.get(name, (None, None)))

    # --- resolve_ex の戻り値契約（環境/レジストリを注入）---
    if resolve_ex("K", _environ={"K": ""}, _query=q({"K": ("REGVAL", None)})) != ("", None):
        fail("#1 empty-string not respected")
    if resolve_ex("K", _environ={}, _query=q({"K": ("REGVAL", None)})) != ("REGVAL", None):
        fail("#3 registry value not returned")
    if resolve_ex("K", _environ={}, _query=q({})) != (None, None):
        fail("missing must be (None,None)")
    if resolve_ex("K", _environ={}, _query=q({"K": (None, "openkey:OSError")})) != (None, "openkey:OSError"):
        fail("#3 infra error not surfaced")

    # --- resolve() は fail-closed（error は例外・round6）---
    saved_rex = globals()["resolve_ex"]
    try:
        globals()["resolve_ex"] = lambda name: (None, "openkey:OSError")
        try:
            resolve("K"); fail("resolve() did not raise on infra error")
        except EnvBootError:
            pass
        globals()["resolve_ex"] = lambda name: (None, None)
        if resolve("K") is not None:
            fail("resolve() should return None for genuine absence")
    finally:
        globals()["resolve_ex"] = saved_rex

    # --- _classify の型契約（round6：直接テスト）---
    if _classify("v", _REG_SZ) != ("v", None):
        fail("classify REG_SZ")
    if _classify(b"x", _REG_SZ)[0] is not None:
        fail("classify non-str REG_SZ must error")
    if _classify("%X%", _REG_EXPAND_SZ) != (None, "reg-expand-unsupported"):
        fail("classify REG_EXPAND must be rejected")
    if _classify(123, 4)[0] is not None:          # REG_DWORD
        fail("classify REG_DWORD must error")

    # --- _query_registry のWindows境界（round6：fake winreg注入で直接テスト）---
    if _query_registry("K", _winreg=_fake_winreg(query_result=("v", _REG_SZ))) != ("v", None):
        fail("query REG_SZ value")
    if _query_registry("K", _winreg=_fake_winreg(query_exc=FileNotFoundError())) != (None, None):
        fail("query missing value must be (None,None)")
    if _query_registry("K", _winreg=_fake_winreg(query_exc=OSError()))[1] is None:
        fail("query access error must surface")
    if _query_registry("K", _winreg=_fake_winreg(open_exc=FileNotFoundError())) != (None, None):
        fail("openkey missing must be (None,None)")
    if _query_registry("K", _winreg=_fake_winreg(open_exc=OSError()))[1] is None:
        fail("openkey access error must surface")
    if _query_registry("K", _winreg=_fake_winreg(query_result=("%X%", _REG_EXPAND_SZ)))[1] != "reg-expand-unsupported":
        fail("query REG_EXPAND must be rejected")

    # os.environ 注入API・列挙・自前展開は撤去済み
    for gone in ("hydrate", "build_child_env", "_snapshot", "_expand"):
        if gone in globals():
            fail("removed API/remnant present: " + gone)

    if dict(os.environ) != env_before:            # 副作用ゼロ（round6/MEDIUM）
        fail("self-test mutated os.environ")

    return ok, ("self-test PASS" if ok else "self-test FAIL: " + "; ".join(msgs))


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        ok, msg = _selftest()
        print(("PASS " if ok else "FAIL ") + msg)   # 機械判定語はASCII（encoding非依存）
        sys.exit(0 if ok else 1)
    # 手動確認用：解決状況をASCIIで表示（注入しない）。インフラ異常があれば exit 非0。
    s = sweep()
    print("env_boot resolve status (read-only, per-key, no injection):")
    for name in KEYS:
        state = "env" if name in s["env"] else ("registry" if name in s["registry"] else "-")
        print("  %-32s %s" % (name, state))
    if s["errors"]:
        print("ERROR registry read anomalies:", s["errors"])
        sys.exit(1)
    sys.exit(0)
