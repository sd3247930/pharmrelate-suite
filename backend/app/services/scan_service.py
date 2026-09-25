"""扫码采集服务：状态机 + 即时拦截 + 冲突审计。

设计要点：

1. **后端权威。** 状态由服务端依据库内数据推导与推进，前端只提交
   "识别到了什么"（`apply_frame`）与"操作员点了什么"（`confirm` / `rescan` / …）。

2. **派生而非记账。** 每次取快照都从批次实际数据推导当前该做什么，
   而不是维护一份可能与库不一致的会话状态。只有"等待确认的条码"这类
   瞬态信息放在内存会话里。

3. **即时拦截。** 前缀层级、同批次去重、溢出都在写入前判定，
   一旦命中就拒绝写入并返回明确的恢复路径（V1.1 10.4 / 38 章）。

4. **冲突落审计。** 同区域幻影码冲突、重复扫码、多码报警、溢出
   全部写入审计日志，便于回溯现场与判断是否需要调整拍摄条件。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from ..domain import scan_state as st
from ..domain.constants import classify_code, layer_label
from ..domain.models import Batch
from ..repositories.audit_repository import AuditRepository
from ..repositories.batch_repository import BatchRecord, BatchRepository

ACTION_SCAN = "scan"
ACTION_CONFLICT = "scan_conflict"
ACTION_ALARM = "scan_alarm"


@dataclass(slots=True)
class ScanSession:
    """一个批次的扫码会话（瞬态部分）。

    持久化的东西一律写进库；这里只留"识别到了码、等操作员确认"这类
    一闪而过的状态，进程重启后重新推导即可。
    """

    batch_id: str
    status: str = st.STATUS_IDLE
    current_can_index: int = 1
    pending_code: str = ""
    last_event: st.ScanEvent | None = None
    conflict_count: int = 0
    """同区域幻影码冲突次数（用于判断是否需要调整拍摄距离或光源）。"""

    rescan_count: int = 0
    alarm_count: int = 0
    reopened: bool = False
    """本罐核对时操作员选了「还没好」→ 回到拍粒子。

    此时本罐往往已经满了，光看数据推导不出"操作员想继续补扫"这个意图
    （数据上罐已满，推导结果会是"进入下一罐"），所以需要这个显式标记。
    一旦补扫成功或进入下一罐就清掉。
    """

    @property
    def has_pending(self) -> bool:
        return self.pending_code != ""


@dataclass(slots=True)
class ScanSnapshot:
    batch_id: str
    status: str
    status_label: str
    current_can_index: int
    planned_can_count: int
    planned_particle_total: int
    actual_particle_total: int
    missing_particles: int
    current_can_planned: int
    current_can_scanned: int
    remaining_in_can: int
    can_complete: bool
    pending_code: str
    last_event: dict[str, object] | None
    conflict_count: int
    alarm_count: int
    can_plan: list[int] = field(default_factory=list)
    can_codes: list[str] = field(default_factory=list)
    can_scanned: list[int] = field(default_factory=list)
    can_particles: list[list[str]] = field(default_factory=list)
    """每罐已扫到的粒子码（按采集顺序）。槽位网格直接用它渲染。"""

    def to_dict(self) -> dict[str, object]:
        return {
            "batchId": self.batch_id,
            "status": self.status,
            "statusLabel": self.status_label,
            "currentCanIndex": self.current_can_index,
            "plannedCanCount": self.planned_can_count,
            "plannedParticleTotal": self.planned_particle_total,
            "actualParticleTotal": self.actual_particle_total,
            "missingParticles": self.missing_particles,
            "currentCanPlanned": self.current_can_planned,
            "currentCanScanned": self.current_can_scanned,
            "remainingInCan": self.remaining_in_can,
            "canComplete": self.can_complete,
            "pendingCode": self.pending_code,
            "lastEvent": self.last_event,
            "conflictCount": self.conflict_count,
            "alarmCount": self.alarm_count,
            "canPlan": self.can_plan,
            "canCodes": self.can_codes,
            "canScanned": self.can_scanned,
            "canParticles": self.can_particles,
        }


class ScanService:
    def __init__(self, repository: BatchRepository, audit: AuditRepository) -> None:
        self._repository = repository
        self._audit = audit
        self._sessions: dict[str, ScanSession] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 会话

    def session(self, batch_id: str) -> ScanSession:
        with self._lock:
            session = self._sessions.get(batch_id)
            if session is None:
                session = ScanSession(batch_id=batch_id)
                self._sessions[batch_id] = session
            return session

    def reset_session(self, batch_id: str) -> None:
        with self._lock:
            self._sessions.pop(batch_id, None)

    # -------------------------------------------------------------- 状态推导

    def _usage_index(self, batch: Batch) -> dict[str, tuple[str, int]]:
        """条码 → (位置描述, 罐序号)。用于重复扫码时告诉操作员"它在哪"。"""

        index: dict[str, tuple[str, int]] = {}
        if batch.box.code.strip():
            index[batch.box.code] = ("箱号", 0)
        for position, can in enumerate(batch.box.cans, start=1):
            if can.code.strip():
                index[can.code] = (f"罐 {position} 号", position)
            for slot, particle in enumerate(can.particles, start=1):
                index[particle] = (f"罐 {position} / 粒子槽位 {slot}", position)
        return index

    def _derive_status(self, batch: Batch, session: ScanSession) -> str:
        """从实际数据推导"现在该做什么"。

        两类状态要分开对待：

        - **可推导的**：等箱号 / 等罐号 / 等粒子 / 整体核对，全部由库内数据算出来。
        - **必须记住的**：本罐核对、下一罐询问、提前结束。这些是"等操作员答复"的
          中间态，光看数据推不出来（罐已经满了，但没有"是否已确认"的痕迹）。

        关键细节：待确认态（box_confirm / can_confirm）只有在**确实还挂着一个待确认条码**
        时才保留。否则确认写入之后 pending 已清空，状态却还停在待确认，
        后续所有动作都会因为"状态不对"被拒绝 —— 这个坑踩过一次。
        """

        if session.status == st.STATUS_EARLY_END:
            return st.STATUS_EARLY_END
        if session.status == st.STATUS_NEXT_CAN_PROMPT:
            return st.STATUS_NEXT_CAN_PROMPT
        if session.status == st.STATUS_CAN_REVIEW:
            return st.STATUS_CAN_REVIEW
        if session.status == st.STATUS_PARTICLE_SCANNING and session.reopened:
            return st.STATUS_PARTICLE_SCANNING
        if session.status in (st.STATUS_BOX_CONFIRM, st.STATUS_CAN_CONFIRM) and session.has_pending:
            return session.status

        plan = batch.planned_particle_counts
        if not plan:
            # 计划为空说明还没生成扫码网格，此时不该在扫码
            return st.STATUS_IDLE
        if not batch.box.code.strip():
            return st.STATUS_BOX_SCANNING

        scanned_by_can = {can.index: len(can.particles) for can in batch.box.cans}
        for index in range(1, len(plan) + 1):
            can = next((item for item in batch.box.cans if item.index == index), None)
            if can is None or not can.code.strip():
                session.current_can_index = index
                return st.STATUS_CAN_SCANNING
            if scanned_by_can.get(index, 0) < plan[index - 1]:
                session.current_can_index = index
                return st.STATUS_PARTICLE_SCANNING

        return st.STATUS_OVERALL_REVIEW

    def snapshot(self, record: BatchRecord) -> ScanSnapshot:
        batch = record.batch
        session = self.session(record.id)
        session.status = self._derive_status(batch, session)

        plan = batch.planned_particle_counts
        index = min(max(1, session.current_can_index), max(1, len(plan)))

        can_codes = [can.code for can in batch.box.cans]
        can_scanned = [len(can.particles) for can in batch.box.cans]
        can_particles = [list(can.particles) for can in batch.box.cans]
        current_planned = plan[index - 1] if 1 <= index <= len(plan) else 0
        current_can = next((item for item in batch.box.cans if item.index == index), None)
        current_scanned = len(current_can.particles) if current_can else 0

        return ScanSnapshot(
            batch_id=record.id,
            status=session.status,
            status_label=st.label_of(session.status),
            current_can_index=index,
            planned_can_count=len(plan),
            planned_particle_total=sum(plan),
            actual_particle_total=batch.actual_particle_total,
            missing_particles=max(0, sum(plan) - batch.actual_particle_total),
            current_can_planned=current_planned,
            current_can_scanned=current_scanned,
            remaining_in_can=max(0, current_planned - current_scanned),
            can_complete=bool(current_planned) and current_scanned >= current_planned,
            pending_code=session.pending_code,
            last_event=session.last_event.to_dict() if session.last_event else None,
            conflict_count=session.conflict_count,
            alarm_count=session.alarm_count,
            can_plan=list(plan),
            can_codes=can_codes,
            can_scanned=can_scanned,
            can_particles=can_particles,
        )

    # ------------------------------------------------------------------ 拦截

    def _check_layer(
        self, codes: list[str], expected_layer: int, batch: Batch, session: ScanSession
    ) -> st.ScanEvent | None:
        """严格单码 + 层级白名单 + 同批次去重。"""

        if not codes:
            return st.event(st.EVENT_NO_CODE, "没有识别到条码，请重新拍摄。")
        if len(codes) > 1:
            session.alarm_count += 1
            return st.event(
                st.EVENT_MULTI_CODE,
                f"当前画面识别到 {len(codes)} 个条码；扫描{layer_label(expected_layer)}号时"
                "要求画面中只出现 1 个条码，请调整镜头重拍。",
                {"detected": codes, "expectedLayer": expected_layer},
            )

        code = codes[0]
        layer = classify_code(code)
        if layer != expected_layer:
            return st.event(
                st.EVENT_WRONG_LAYER,
                f"条码 {code} 是「{layer_label(layer)}」，此处需要「{layer_label(expected_layer)}」。",
                {"code": code, "actualLayer": layer, "expectedLayer": expected_layer},
            )

        used = self._usage_index(batch)
        if code in used:
            where, can_index = used[code]
            return st.event(
                st.EVENT_DUPLICATE_CODE,
                f"条码 {code} 已被使用于「{where}」，请勿重复扫码。",
                {"code": code, "usedAt": where, "canIndex": can_index},
            )
        return None

    def _record(
        self,
        batch_id: str,
        action: str,
        result: str,
        event_obj: st.ScanEvent | None,
        *,
        payload: dict[str, object] | None = None,
        reason: str | None = None,
    ) -> None:
        self._audit.append(
            action=action,
            entity="scan",
            entity_id=batch_id,
            result=result,
            new_value=payload,
            reason=reason or (event_obj.code if event_obj else None),
        )

    # -------------------------------------------------------------- 识别入参

    def apply_frame(
        self,
        record: BatchRecord,
        *,
        codes: list[str],
        conflicts: list[dict[str, object]] | None = None,
        engine_version: str = "",
        variants: list[str] | None = None,
    ) -> ScanSnapshot:
        """把一帧的识别结果交给状态机。

        `conflicts` 来自识别层的同区域冲突判定。只要存在冲突就整帧拒绝：
        幻影码同样是 20 位合法前缀，格式校验拦不住它，只能靠"不采信"来防。
        """

        batch = record.batch
        session = self.session(record.id)
        session.status = self._derive_status(batch, session)

        if conflicts:
            session.conflict_count += 1
            self._record(
                record.id,
                ACTION_CONFLICT,
                "blocked",
                None,
                payload={
                    "conflicts": conflicts,
                    "engineVersion": engine_version,
                    "variants": variants or [],
                    "detectedCodes": codes,
                },
                reason=st.EVENT_CONFLICT,
            )
            session.last_event = st.event(
                st.EVENT_CONFLICT,
                "同一位置解出多个不同条码，可能是污损或反光导致误读，请重扫。",
                {"conflicts": conflicts},
            )
            return self.snapshot(record)

        status = session.status

        if status == st.STATUS_BOX_SCANNING:
            blocked = self._check_layer(codes, 3, batch, session)
            if blocked:
                self._record(record.id, ACTION_ALARM if blocked.needs_alarm else ACTION_SCAN,
                             "blocked", blocked, payload={"codes": codes})
                session.last_event = blocked
                return self.snapshot(record)
            session.pending_code = codes[0]
            session.status = st.STATUS_BOX_CONFIRM
            session.last_event = st.event(st.EVENT_OK, f"识别到箱号 {codes[0]}，请确认。")
            return self.snapshot(record)

        if status == st.STATUS_CAN_SCANNING:
            blocked = self._check_layer(codes, 2, batch, session)
            if blocked:
                self._record(record.id, ACTION_ALARM if blocked.needs_alarm else ACTION_SCAN,
                             "blocked", blocked, payload={"codes": codes})
                session.last_event = blocked
                return self.snapshot(record)
            session.pending_code = codes[0]
            session.status = st.STATUS_CAN_CONFIRM
            session.last_event = st.event(
                st.EVENT_OK,
                f"识别到 {codes[0]}，这是罐 {session.current_can_index} 号吗？",
            )
            return self.snapshot(record)

        if status == st.STATUS_PARTICLE_SCANNING:
            applied, blocked = self._apply_particles(record, session, codes)
            return self.snapshot(applied)

        session.last_event = st.event(
            st.EVENT_WRONG_STATE,
            f"当前状态为「{st.label_of(status)}」，不接受新的识别结果。",
        )
        return self.snapshot(record)

    def _apply_particles(
        self, record: BatchRecord, session: ScanSession, codes: list[str]
    ) -> tuple[BatchRecord, st.ScanEvent | None]:
        """粒子批量入格：层级 → 去重 → 溢出，三道拦截依次过。"""

        batch = record.batch
        index = session.current_can_index
        can = next((item for item in batch.box.cans if item.index == index), None)
        if can is None or not can.code.strip():
            session.last_event = st.event(
                st.EVENT_WRONG_STATE, f"罐 {index} 还没有罐号，无法录入粒子。"
            )
            return record, session.last_event

        # 1) 层级白名单
        wrong = [(code, classify_code(code)) for code in codes if classify_code(code) != 1]
        if wrong:
            bad_code, actual = wrong[0]
            blocked = st.event(
                st.EVENT_WRONG_LAYER,
                f"条码 {bad_code} 是「{layer_label(actual)}」，粒子扫描只接受粒子码。",
                {"code": bad_code, "actualLayer": actual, "expectedLayer": 1},
            )
            session.last_event = blocked
            self._record(record.id, ACTION_SCAN, "blocked", blocked, payload={"codes": codes})
            return record, blocked

        # 2) 本次识别内部的重复
        seen: set[str] = set()
        duplicates: list[str] = []
        for code in codes:
            if code in seen and code not in duplicates:
                duplicates.append(code)
            seen.add(code)
        if duplicates:
            session.alarm_count += 1
            blocked = st.event(
                st.EVENT_DUPLICATE_CODE,
                f"本次识别中有 {len(duplicates)} 个条码重复出现，请检查后重扫。",
                {"duplicates": duplicates},
            )
            session.last_event = blocked
            self._record(record.id, ACTION_ALARM, "blocked", blocked, payload={"codes": codes})
            return record, blocked

        # 3) 与批次内已有条码的重复（要告诉操作员它已绑在哪里）
        used = self._usage_index(batch)
        already = [code for code in codes if code in used]
        if already:
            where, can_index = used[already[0]]
            blocked = st.event(
                st.EVENT_DUPLICATE_CODE,
                f"条码 {already[0]} 已被使用于「{where}」，请勿重复扫码。",
                {"code": already[0], "usedAt": where, "canIndex": can_index, "duplicates": already},
            )
            session.last_event = blocked
            self._record(record.id, ACTION_SCAN, "blocked", blocked, payload={"codes": codes})
            return record, blocked

        # 4) 溢出拦截：整批拒绝，不做部分写入
        planned = (
            batch.planned_particle_counts[index - 1]
            if 1 <= index <= len(batch.planned_particle_counts)
            else 0
        )
        scanned = len(can.particles)
        remaining = max(0, planned - scanned)
        if len(codes) > remaining:
            session.alarm_count += 1
            blocked = st.event(
                st.EVENT_OVERFLOW,
                f"罐 {index} 计划 {planned} 粒，已扫 {scanned} 粒，仅剩 {remaining} 个槽位，"
                f"本次识别到 {len(codes)} 个。已拒绝写入，请检查是否重复扫码或计划数设置。",
                {
                    "planned": planned,
                    "scanned": scanned,
                    "remaining": remaining,
                    "incoming": len(codes),
                },
            )
            session.last_event = blocked
            self._record(record.id, ACTION_ALARM, "blocked", blocked, payload={"codes": codes})
            return record, blocked

        updated = self._repository.append_particles(record.id, can.code, list(codes))
        if updated is None:  # pragma: no cover
            return record, None
        session.reopened = False

        self._record(
            record.id,
            ACTION_SCAN,
            "success",
            None,
            payload={"canIndex": index, "canCode": can.code, "codes": list(codes)},
        )

        scanned_after = scanned + len(codes)
        if planned and scanned_after >= planned:
            session.status = st.STATUS_CAN_REVIEW
            session.last_event = st.event(
                st.EVENT_OK,
                f"罐 {index} 已扫满 {planned} 粒，请检查无误后确认。",
                {"canIndex": index, "scanned": scanned_after, "planned": planned},
            )
        else:
            session.last_event = st.event(
                st.EVENT_OK,
                f"本次加入 {len(codes)} 粒，罐 {index} 进度 {scanned_after}/{planned}。",
                {"canIndex": index, "scanned": scanned_after, "planned": planned},
            )
        return updated, session.last_event

    # -------------------------------------------------------------- 操作员动作

    def confirm(self, record: BatchRecord) -> ScanSnapshot:
        """操作员确认：箱号 / 罐号 / 本罐满额。"""

        session = self.session(record.id)
        session.status = self._derive_status(record.batch, session)

        if session.status == st.STATUS_BOX_CONFIRM:
            code = session.pending_code
            self._repository.set_box_code(record.id, code)
            session.pending_code = ""
            refreshed = self._repository.get(record.id)
            assert refreshed is not None
            self._record(record.id, "scan_box", "success", None, payload={"boxCode": code})
            session.status = self._derive_status(refreshed.batch, session)
            session.last_event = st.event(st.EVENT_OK, f"箱号 {code} 已确认。")
            return self.snapshot(refreshed)

        if session.status == st.STATUS_CAN_CONFIRM:
            code = session.pending_code
            index = session.current_can_index
            planned = (
                record.batch.planned_particle_counts[index - 1]
                if 1 <= index <= len(record.batch.planned_particle_counts)
                else 0
            )
            self._repository.add_can(record.id, code, planned)
            session.pending_code = ""
            refreshed = self._repository.get(record.id)
            assert refreshed is not None
            self._record(
                record.id,
                "scan_can",
                "success",
                None,
                payload={"canIndex": index, "canCode": code, "planned": planned},
            )
            session.status = self._derive_status(refreshed.batch, session)
            session.last_event = st.event(
                st.EVENT_OK, f"罐 {index} 号 {code} 已确认，请开始扫描粒子。"
            )
            return self.snapshot(refreshed)

        if session.status == st.STATUS_CAN_REVIEW:
            index = session.current_can_index
            total = len(record.batch.planned_particle_counts)
            session.reopened = False
            if index < total:
                session.status = st.STATUS_NEXT_CAN_PROMPT
                session.last_event = st.event(
                    st.EVENT_OK, f"罐 {index} 已完成，是否继续扫描罐 {index + 1}？"
                )
            else:
                session.status = st.STATUS_OVERALL_REVIEW
                session.last_event = st.event(
                    st.EVENT_OK, "所有罐已完成，请进行整体核对。"
                )
            return self.snapshot(record)

        raise st.ScanError(session.status, "确认")

    def rescan(self, record: BatchRecord) -> ScanSnapshot:
        """重拍：丢弃待确认的条码；本罐核对时退回继续拍摄。"""

        session = self.session(record.id)
        session.status = self._derive_status(record.batch, session)
        session.rescan_count += 1

        if session.status in (st.STATUS_BOX_CONFIRM, st.STATUS_CAN_CONFIRM):
            session.pending_code = ""
            session.status = (
                st.STATUS_BOX_SCANNING
                if session.status == st.STATUS_BOX_CONFIRM
                else st.STATUS_CAN_SCANNING
            )
            self._record(record.id, "rescan", "success", None, reason="操作员选择重拍")
            session.last_event = st.event(st.EVENT_OK, "已清除本次识别结果，请重新拍摄。")
            return self.snapshot(record)

        if session.status == st.STATUS_CAN_REVIEW:
            session.status = st.STATUS_PARTICLE_SCANNING
            session.reopened = True
            self._record(record.id, "rescan", "success", None, reason="本罐未确认，继续补扫")
            session.last_event = st.event(st.EVENT_OK, "继续补扫本罐粒子。")
            return self.snapshot(record)

        raise st.ScanError(session.status, "重拍")

    def next_can(self, record: BatchRecord, *, proceed: bool) -> ScanSnapshot:
        """下一罐询问的答复。proceed=False 表示提前结束。"""

        session = self.session(record.id)
        if session.status != st.STATUS_NEXT_CAN_PROMPT:
            raise st.ScanError(session.status, "下一罐询问")

        if proceed:
            session.current_can_index += 1
            session.status = st.STATUS_CAN_SCANNING
            session.reopened = False
            self._record(
                record.id,
                "next_can",
                "success",
                None,
                payload={"canIndex": session.current_can_index},
            )
            session.last_event = st.event(
                st.EVENT_OK, f"请扫描罐 {session.current_can_index} 号。"
            )
            return self.snapshot(record)

        session.status = st.STATUS_EARLY_END
        self._record(
            record.id,
            "early_end_requested",
            "pending",
            None,
            reason="操作员选择提前结束，等待填写原因与签名",
        )
        session.last_event = st.event(
            st.EVENT_OK, "已进入提前结束流程，请填写原因并选择操作人。"
        )
        return self.snapshot(record)

    # ------------------------------------------------------------------ 审计

    def record_alarm(
        self, batch_id: str, event_code: str, message: str, detail: dict[str, object] | None = None
    ) -> None:
        """把一次报警写入审计（多码报警等由 I/O 层触发的事件）。"""

        session = self.session(batch_id)
        session.alarm_count += 1
        self._record(
            batch_id,
            ACTION_ALARM,
            "blocked",
            None,
            payload=detail or {},
            reason=event_code,
        )
        session.last_event = st.event(event_code, message, detail)
