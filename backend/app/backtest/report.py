"""A backtest as a text report (Markdown), laid out like the 검증 기준 table of PRD 10장.

The report only *describes* the run: how big the samples are, what was compared with what, and
which checks failed. It never recommends a parameter and never changes one. Settling the PRD 6장
defaults from real data stays a human decision.
"""

from typing import Any


def _pct(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{100 * value:+.{digits}f}%"


def _plain_pct(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{100 * value:.{digits}f}%"


def _num(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    return [_row(header), _row(["---"] * len(header)), *(_row(r) for r in rows), ""]


def _quality(quality: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    out = ["## 1. 신호 품질 (스크리너 후보)", ""]
    cands = quality["candidates"]
    adoption = quality["adoption"]
    out += [
        f"- 평가 구간 {quality['period']['start']} ~ {quality['period']['end']} "
        f"({quality['period']['sessions']}거래일), 계산 엔진 `{quality['engine']}`",
        f"- 체결 가정: 신호 다음 거래일 시가 진입, 보유 기간 후 시가 청산, 한쪽 수수료 "
        f"{_plain_pct(quality['costs']['fee_per_side'], 3)}, 기준 슬리피지 "
        f"{_plain_pct(quality['costs']['base_slippage'], 2)}",
        f"- 후보 수: 일평균 {cands['per_day_mean']:.2f}개, 후보 0건인 날 {cands['zero_days']}일 "
        f"({_plain_pct(cands['zero_days_share'])}), 게이트 방식 {cands['gate_modes']}",
        f"- 표본: 신호가 난 날 {adoption['n_dates']}일 (최소 {adoption['min_sample_dates']}일) "
        f"→ **{'기준 충족' if adoption['adoptable'] else '표본 부족, 채택하지 않음'}**",
        "",
        "### 보유 기간별 수익률 (비용 반영)",
        "",
    ]
    rows = []
    for h, block in quality["horizons"].items():
        for label, key in (
            ("후보", "strategy"),
            ("유니버스 전체", "universe"),
            ("무작위 진입", "random"),
            ("KOSPI", "kospi"),
        ):
            s = block[key]
            if not s.get("n_events"):
                rows.append([h + "일", label, "0", "-", "-", "-", "-", "-", "-"])
                continue
            rows.append(
                [
                    h + "일",
                    label,
                    str(s["n_events"]),
                    str(s["n_dates"]),
                    _pct(s["mean"]),
                    _pct(s["median"]),
                    _plain_pct(s["win_rate"]),
                    _num(s.get("payoff_ratio")),
                    _num(s.get("profit_factor")),
                ]
            )
    out += _table(
        ["기간", "대상", "표본(건)", "표본(일)", "평균", "중앙값", "승률", "손익비", "PF"], rows
    )

    port = quality["portfolios"]
    out += [
        f"### 포트폴리오 지표 (보유 {port['horizon']}일, 같은 기간, 노출 {_plain_pct(port['exposure'])})",
        "",
    ]
    names = (("후보", "strategy"), ("유니버스 단순 보유", "universe"), ("KOSPI", "kospi"))
    rows = [[n, *_ratio_cells(port[k])] for n, k in names]
    rows.append(["무작위 진입 (평균)", *_ratio_cells(port["random"]["mean"])])
    out += _table(["대상", "총수익", "연환산", "Sharpe", "Sortino", "Calmar", "최대낙폭"], rows)

    rows = []
    for name, label in (("up", "상승"), ("down", "하락"), ("flat", "횡보")):
        block = quality["regimes"][name]
        s, u = block["strategy"], block["universe"]
        rows.append(
            [
                label,
                str(block["days"]),
                str(s.get("n_events", 0)),
                _pct(s.get("mean")),
                _pct(s.get("median")),
                _pct(u.get("mean")),
            ]
        )
    out += ["### 시장 국면별 (KOSPI 기준, 후보 vs 유니버스)", ""]
    out += _table(["국면", "일수", "후보 표본", "후보 평균", "후보 중앙값", "유니버스 평균"], rows)

    out += ["### 슬리피지 민감도", ""]
    out += _table(
        ["슬리피지", "후보 평균", "후보 중앙값", "승률", "유니버스 평균", "차이"],
        [
            [
                _plain_pct(r["slippage"], 2),
                _pct(r["mean"]),
                _pct(r["median"]),
                _plain_pct(r["win_rate"]),
                _pct(r["universe_mean"]),
                _pct(r["edge"]),
            ]
            for r in quality["slippage"]
        ],
    )
    return out


def _ratio_cells(r: dict[str, float | None]) -> list[str]:
    return [
        _pct(r["total_return"]),
        _pct(r["annualized_return"]),
        _num(r["sharpe"]),
        _num(r["sortino"]),
        _num(r["calmar"]),
        _pct(r["max_drawdown"]),
    ]


def _cycle(cycle: dict[str, Any]) -> list[str]:
    m = cycle["metrics"]
    out = ["## 2. 수량 늘리기 (사이클 시뮬레이션)", ""]
    out += [
        f"- 구간 {cycle['period']['start']} ~ {cycle['period']['end']}, 봉 길이 {m['bar_length']}, "
        f"종목 {m['stocks']}개, 슬리피지 {_plain_pct(m['slippage'], 2)}",
        f"- 사이클 성공률(재매수 완료 / 끝난 매도): {_plain_pct(m['completion_rate'])} "
        f"({m['completed']} / {m['finished']}), 수량이 실제로 늘어난 비율 {_plain_pct(m['gain_rate'])}",
        f"- 사이클당 수량 증가율: 평균 {_pct(m['increase_rate']['mean'])}, 중앙값 {_pct(m['increase_rate']['median'])}, "
        f"누적 수량 증가 {m['cumulative_increase']}주 ({_pct((m['cumulative_increase_pct'] or 0) / 100)})",
        f"- 평균 재매수 소요 {_num(m['wait_sessions']['mean'])}거래일 (중앙값 {_num(m['wait_sessions']['median'])})",
        f"- 만료 {m['expired']}건 ({_plain_pct(m['expired_share'])}), 만료 건의 기회손실: 평균 "
        f"{_num(m['missed_pct']['mean'])}% 상승을 놓침, 합계 {m['missed_value']:,.0f}원",
        f"- 강제 매도(5일선 이탈) {m['forced']['count']}회 ({m['forced']['stocks']}종목)",
        f"- 수익률 {_pct(m['total_return'])} vs 매도 없이 보유 {_pct(m['hold_return'])} "
        f"(차이 {_pct(m['excess_return'])}), 최대 낙폭 {_pct(m['max_drawdown'])} (보유 {_pct(m['hold_max_drawdown'])})",
        f"- 수수료·거래세 합계 {m['costs']:,.0f}원",
        "",
    ]
    after = m["forced"]["after"]
    if any(v["n"] for v in after.values()):
        out += ["### 강제 매도 이후 수익률 (매도가 대비)", ""]
        out += _table(
            ["이후", "표본", "평균", "중앙값"],
            [
                [f"{h}거래일", str(v["n"]), _pct(v["mean"]), _pct(v["median"])]
                for h, v in after.items()
            ],
        )
    out += ["### 슬리피지를 올려도 수량 증가가 유지되는가", ""]
    out += _table(
        ["슬리피지", "매도", "성공률", "평균 증가율", "누적 증가", "수익률"],
        [
            [
                _plain_pct(r["slippage"], 2),
                str(r["finished"]),
                _plain_pct(r["completion_rate"]),
                _pct(r["mean_increase_rate"]),
                f"{r['cumulative_increase']}주",
                _pct(r["total_return"]),
            ]
            for r in cycle["slippage"]
        ],
    )
    if cycle["comparison"]:
        out += ["## 3. 봉 길이 비교 (같은 기간, 같은 종목, 같은 신호 코드)", ""]
        out += _table(
            [
                "봉",
                "끝난 매도",
                "신호 발생일",
                "성공률",
                "평균 증가율",
                "누적 증가",
                "수익률",
                "최대낙폭",
                "표본",
            ],
            [
                [
                    r["bar_length"],
                    str(r["finished"]),
                    str(r["signal_dates"]),
                    _plain_pct(r["completion_rate"]),
                    _pct(r["mean_increase_rate"]),
                    f"{r['cumulative_increase']}주",
                    _pct(r["total_return"]),
                    _pct(r["max_drawdown"]),
                    "충족" if r["adoption"]["adoptable"] else "부족",
                ]
                for r in cycle["comparison"]
            ],
        )
        out += [
            "봉 길이가 길수록 신호 표본이 줄어듭니다. 표본이 부족한 행의 비율은 비교 대상으로 삼지 마세요.",
            "",
        ]
    return out


def _sensitivity(grid: dict[str, Any]) -> list[str]:
    x, y = grid["x"], grid["y"]
    out = [
        "## 4. 파라미터 민감도",
        "",
        f"- 평가 지표 `{grid['metric']}` ({grid['target']}), 칸마다 표본이 "
        f"{grid['min_samples']:g}건 미만이면 제외",
    ]
    xs = x["values"]
    ys = y["values"] if y else [None]
    header = [f"{y['path'] if y else ''} \\ {x['path']}", *[f"{v:g}" for v in xs]]
    rows = []
    for iy, yv in enumerate(ys):
        rows.append(
            [f"{yv:g}" if yv is not None else "-"]
            + [
                (f"{c:.4f}" if c is not None else "-") + f" (n={n})"
                for c, n in zip(grid["cells"][iy], grid["samples"][iy], strict=True)
            ]
        )
    out += ["", *_table(header, rows)]
    best, robust = grid["best"], grid["robust_best"]
    out += [
        f"- 기본값: {x['path']}={x['default']:g}"
        + (f", {y['path']}={y['default']:g}" if y else ""),
        f"- 가장 높은 칸: {best}" if best else "- 가장 높은 칸: 없음",
        f"- 주변 3x3 평균이 가장 높은 칸(고르게 좋은 구간): {robust}"
        if robust
        else "- 고르게 좋은 구간: 없음",
        "",
    ]
    return out


def _walk_forward(wf: dict[str, Any]) -> list[str]:
    out = ["## 5. 롤링(walk-forward) 검증", ""]
    out.append(
        f"- 파라미터 `{wf['param']}` 후보 {wf['values']} (기본 {wf['default']:g}), 지표 `{wf['metric']}`, "
        f"학습 {wf['train_days']}일 / 검증 {wf['test_days']}일 / 이동 {wf['step_days']}일"
    )
    if not wf["folds"]:
        return [*out, f"- 실행하지 못했습니다: {wf.get('reason', '')}", ""]
    out += [""]
    out += _table(
        ["구간", "학습", "검증", "고른 값", "학습 지표", "검증 지표", "기본값 검증 지표"],
        [
            [
                str(f["fold"]),
                f"{f['train'][0]}~{f['train'][1]}",
                f"{f['test'][0]}~{f['test'][1]}",
                "-" if f["chosen"] is None else f"{f['chosen']:g}",
                _num(f["train_metric"], 4),
                _num(f["test_metric"], 4),
                _num(f["default_test_metric"], 4),
            ]
            for f in wf["folds"]
        ],
    )
    s = wf["summary"]
    out += [
        f"- 구간 {s['folds']}개: 학습 평균 {_num(s['mean_train_metric'], 4)}, 검증 평균 "
        f"{_num(s['mean_test_metric'], 4)}, 기본값을 그대로 쓴 검증 평균 {_num(s['mean_default_test_metric'], 4)}",
        f"- 검증/학습 비율 {_num(s['efficiency'])} (1보다 많이 낮으면 학습 구간에만 맞춘 것), "
        f"고른 값의 종류 {s['chosen_changes']}가지",
        "",
    ]
    return out


def build_report(
    name: str | None, params: dict[str, Any], summary: dict[str, Any], detail: dict[str, Any]
) -> str:
    """The Markdown report of one finished run."""
    data = summary["data"]
    notes = data["notes"]
    lines = [
        f"# 백테스트 리포트{': ' + name if name else ''}",
        "",
        "신호와 상태 머신은 앱이 쓰는 코드를 그대로 썼습니다. 이 문서는 결과를 설명할 뿐이며 "
        "6장 기본값을 정하는 일은 하지 않습니다.",
        "",
        "## 0. 데이터와 가정",
        "",
        f"- 기간 {summary['period']['start']} ~ {summary['period']['end']}, 종목 {data['stocks']}개, "
        f"거래일 {data['sessions']}일",
        f"- 수정주가 사용: {'예' if notes.get('adjusted_prices') else '아니오'}",
        f"- 유니버스: {notes.get('universe', '-')} (저장된 시점 스냅샷 {notes.get('snapshots', 0)}개)",
        f"- 상장폐지 종목 포함: {'예' if notes.get('include_delisted', True) else '아니오 (생존 종목만)'}"
        f"{', 대상 ' + ', '.join(data['delisted']) if data['delisted'] else ''}",
    ]
    if "intraday_span" in notes:
        a, b = notes["intraday_span"]
        lines.append(f"- 분봉 보관 구간 {a[:10]} ~ {b[:10]}")
    lines.append("")
    if summary["warnings"]:
        lines += ["**주의**", "", *[f"- {w}" for w in summary["warnings"]], ""]
    if "signal_quality" in detail:
        lines += _quality(detail["signal_quality"], summary)
    if "cycle" in detail:
        lines += _cycle(detail["cycle"])
    if "sensitivity" in detail:
        lines += _sensitivity(detail["sensitivity"])
    if "walk_forward" in detail:
        lines += _walk_forward(detail["walk_forward"])
    lines += [
        "## 부록. 실행 파라미터",
        "",
        "```json",
        _dump(params),
        "```",
        "",
    ]
    return "\n".join(lines)


def _dump(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
