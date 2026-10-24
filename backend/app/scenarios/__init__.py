"""Independent, reproducible synthetic datasets; loading never mutates a seed."""
from copy import deepcopy
from uuid import NAMESPACE_URL, UUID, uuid5
from .seeds import baseline, scenario_one

_REGISTRY = {}


def register_scenario(identifier, name, description, factory):
    if identifier in _REGISTRY:
        raise ValueError(f"Scenario already registered: {identifier}")
    _REGISTRY[identifier] = (name, description, factory)


def list_scenarios():
    return [{"id": key, "name": value[0], "description": value[1], "is_synthetic": True}
            for key, value in _REGISTRY.items()]


def load_scenario(identifier):
    if identifier not in _REGISTRY:
        raise KeyError(f"Unknown scenario: {identifier}")
    name, description, factory = _REGISTRY[identifier]
    data = deepcopy(factory())
    def scope(value):
        if isinstance(value, dict):
            return {key: scope(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scope(item) for item in value]
        if isinstance(value, str):
            try:
                UUID(value)
            except ValueError:
                return value
            return str(uuid5(NAMESPACE_URL, f"bio-erp/scenario/{identifier}/{value}"))
        return value
    data = scope(data)
    data.update(id=identifier, name=name, description=description)
    return data


register_scenario("scenario_1", "IL-7 분할 발주", "합성 IL-7: 대량 할인과 3회 분할입고의 납기·폐기·총비용 비교", scenario_one)
register_scenario("scenario_1_qc_bottleneck", "IL-7 QC 병목", "독립 변형: 2차 입고 QC가 3일 지연되어 11월 11일 부족", lambda: scenario_one(qc_bottleneck=True))
register_scenario("baseline", "CHO 배지 기본 시나리오", "별도 CHO 배경: 온도별 3원료, 4업체, 공간·품질·예산 검증", baseline)
