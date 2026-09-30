"""
ELOS — FHIRPatientMapper
Converte recursos FHIR R4 do RNDS para entidades do grafo ELOS.
Fonte: Seção E do doc 03_Integracao-APIs-FHIR

DESIGN:
  - CPF nunca armazenado em texto simples — apenas SHA-256 + salt de instância
  - nome_social: prioridade 'usual' > 'official' (respeito à identidade)
  - _trigger_ppr: True quando deceasedBoolean=True → dispara Script 18 automaticamente
"""
from __future__ import annotations

import hashlib
from typing import Optional

# Mapeamento de gênero FHIR → ELOS
# BUG-02 CORRIGIDO: settings removido do módulo-level; FHIRPatientMapper recebe salt via __init__
_GENDER_MAP: dict[str, Optional[str]] = {
    "male": "M",
    "female": "F",
    "other": "O",
    "unknown": None,
}

# Sistemas de identificadores FHIR conhecidos no SUS
_CPF_SYSTEM  = "urn:oid:2.16.840.1.113883.13.237"   # CPF
_CNS_SYSTEM  = "urn:oid:2.16.840.1.113883.13.236"   # CNS


class FHIRPatientMapper:
    """
    Uso:
        mapper = FHIRPatientMapper(settings.cpf_hash_salt)
        elos_pessoa = mapper.map(fhir_patient_dict)
    """

    def __init__(self, instance_salt: str) -> None:
        self._salt = instance_salt

    def map(self, fhir_patient: dict) -> dict:
        """
        Transforma um recurso FHIR Patient (R4) no dicionário
        compatível com CYPHER_CRIAR_PESSOA do Neo4jService.
        """
        cpf = self._extract_identifier(fhir_patient, _CPF_SYSTEM)
        cns = self._extract_identifier(fhir_patient, _CNS_SYSTEM)
        deceased = (
            fhir_patient.get("deceasedBoolean", False)
            or fhir_patient.get("deceasedDateTime") is not None
        )

        return {
            "id":               fhir_patient.get("id") or self._generate_id(cpf, cns),
            "rnds_id":          fhir_patient.get("id"),
            "cpf_hash":         self._hash_cpf(cpf) if cpf else None,
            "cns":              cns,
            "nome_social":      self._extract_preferred_name(fhir_patient),
            "data_nascimento":  fhir_patient.get("birthDate"),
            "sexo_biologico":   _GENDER_MAP.get(fhir_patient.get("gender", "unknown")),
            "municipio":        self._extract_city(fhir_patient),
            "uf":               self._extract_state(fhir_patient),
            "ativo":            not deceased,
            "fonte_dados":      "RNDS",
            "_trigger_ppr":     deceased,   # → Script 18 se True
        }

    def map_encounter(self, fhir_encounter: dict, pessoa_id: str) -> dict:
        """
        Transforma FHIR Encounter R4 → (:EVENTO) do grafo ELOS.
        """
        period = fhir_encounter.get("period", {})
        class_code = fhir_encounter.get("class", {}).get("code", "AMB")

        tipo_map = {
            "AMB": "CONSULTA_AMBULATORIAL",
            "IMP": "INTERNACAO",
            "EMER": "URGENCIA_EMERGENCIA",
            "HH": "ATENCAO_DOMICILIAR",
        }

        return {
            "id":            fhir_encounter.get("id"),
            "rnds_id":       fhir_encounter.get("id"),
            "pessoa_id":     pessoa_id,
            "tipo":          tipo_map.get(class_code, "CONSULTA_AMBULATORIAL"),
            "inicio":        period.get("start"),
            "fim":           period.get("end"),
            "status_fhir":   fhir_encounter.get("status"),
            "servico_id":    self._extract_organization_id(fhir_encounter),
            "fonte_dados":   "RNDS",
        }

    def map_organization(self, fhir_org: dict) -> dict:
        """FHIR Organization → (:SERVICO) do grafo."""
        cnes = self._extract_identifier(fhir_org, "https://rnds-fhir.saude.gov.br/NamingSystem/CNES")
        return {
            "id":           fhir_org.get("id"),
            "rnds_id":      fhir_org.get("id"),
            "cnes":         cnes,
            "nome":         fhir_org.get("name"),
            "tipo":         fhir_org.get("type", [{}])[0].get("coding", [{}])[0].get("code"),
            "ativo":        fhir_org.get("active", True),
            "municipio":    self._extract_city(fhir_org),
            "uf":           self._extract_state(fhir_org),
            "fonte_dados":  "RNDS",
        }

    # ── Helpers privados ──────────────────────────────────────────────────────

    def _hash_cpf(self, cpf: str) -> str:
        """SHA-256 com salt de instância. Irreversível."""
        cpf_limpo = "".join(d for d in cpf if d.isdigit())
        valor = f"{cpf_limpo}{self._salt}"
        return hashlib.sha256(valor.encode()).hexdigest()

    def _generate_id(self, cpf: Optional[str], cns: Optional[str]) -> str:
        """Gera ID ELOS quando RNDS não provê id próprio."""
        import uuid
        base = cpf or cns or str(uuid.uuid4())
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"elos.{base}"))

    def _extract_identifier(self, resource: dict, system: str) -> Optional[str]:
        for ident in resource.get("identifier", []):
            if ident.get("system") == system:
                return ident.get("value")
        return None

    def _extract_preferred_name(self, patient: dict) -> Optional[str]:
        """Prioriza 'usual' (nome social) sobre 'official'."""
        names = patient.get("name", [])
        for use in ("usual", "official"):
            for name in names:
                if name.get("use") == use:
                    text = name.get("text")
                    if text:
                        return text
                    parts = name.get("given", []) + [name.get("family", "")]
                    return " ".join(p for p in parts if p).strip() or None
        # Fallback: primeiro nome disponível
        if names:
            return names[0].get("text") or names[0].get("family")
        return None

    def _extract_city(self, resource: dict) -> Optional[str]:
        """Extrai código IBGE do município via extension 'ibge-municipio'.
        Fallback: nome do campo 'city' se extension ausente.
        BUG-05 CORRIGIDO: municipio deve ser código IBGE, não nome da cidade.
        """
        for addr in resource.get("address", []):
            # Prioridade: extension ibge-municipio (código ELOS padrão)
            for ext in addr.get("extension", []):
                if ext.get("url") in ("ibge-municipio", "http://www.saude.gov.br/fhir/r4/StructureDefinition/BRMunicipio-1.0"):
                    codigo = ext.get("valueString") or ext.get("valueCoding", {}).get("code")
                    if codigo:
                        return codigo
            # Fallback: nome da cidade (menos preciso — não deve ser usado para escopo territorial)
            city = addr.get("city")
            if city:
                return city
        return None

    def _extract_state(self, resource: dict) -> Optional[str]:
        for addr in resource.get("address", []):
            state = addr.get("state")
            if state:
                return state
        return None

    def _extract_organization_id(self, encounter: dict) -> Optional[str]:
        service_provider = encounter.get("serviceProvider", {})
        ref = service_provider.get("reference", "")
        if "/" in ref:
            return ref.split("/")[-1]
        return None
