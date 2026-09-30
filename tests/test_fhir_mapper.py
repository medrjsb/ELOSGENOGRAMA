"""
ELOS — Testes: FHIRPatientMapper
Valida mapeamento FHIR R4 Patient → :PESSOA no grafo ELOS.
"""
import pytest
import hashlib
from uuid import uuid4

from app.services.fhir_mapper import FHIRPatientMapper


SALT = "test-cpf-salt-elos"
CPF_SISTEMA = "urn:oid:2.16.840.1.113883.13.237"
CNS_SISTEMA = "urn:oid:2.16.840.1.113883.13.236"


@pytest.fixture
def mapper():
    return FHIRPatientMapper(instance_salt=SALT)


@pytest.fixture
def fhir_patient_completo():
    """Paciente FHIR R4 com todos os campos relevantes."""
    return {
        "resourceType": "Patient",
        "id": "rnds-patient-001",
        "identifier": [
            {"system": CPF_SISTEMA, "value": "123.456.789-00"},
            {"system": CNS_SISTEMA, "value": "987654321098765"},
        ],
        "name": [
            {
                "use": "official",
                "text": "João da Silva Santos",
                "family": "Santos",
                "given": ["João", "da", "Silva"],
            },
            {
                "use": "usual",
                "text": "Joãozinho Santos",
            },
        ],
        "birthDate": "1985-03-20",
        "gender": "male",
        "address": [
            {
                "city": "Recife",
                "state": "PE",
                "extension": [
                    {
                        "url": "ibge-municipio",
                        "valueString": "PE260790",
                    }
                ],
            }
        ],
        "deceasedBoolean": False,
    }


@pytest.fixture
def fhir_patient_obito():
    """Paciente FHIR R4 marcado como falecido."""
    return {
        "resourceType": "Patient",
        "id": "rnds-patient-002",
        "identifier": [
            {"system": CPF_SISTEMA, "value": "987.654.321-00"},
        ],
        "name": [{"use": "official", "text": "Maria Oliveira"}],
        "birthDate": "1940-01-01",
        "gender": "female",
        "deceasedBoolean": True,
    }


@pytest.fixture
def fhir_patient_sem_cpf():
    """Paciente FHIR R4 sem CPF (só CNS)."""
    return {
        "resourceType": "Patient",
        "id": "rnds-patient-003",
        "identifier": [
            {"system": CNS_SISTEMA, "value": "111222333444555"},
        ],
        "name": [{"use": "official", "text": "Sem CPF Silva"}],
        "birthDate": "2000-06-15",
        "gender": "unknown",
    }


# ─────────────────────────────────────────────────────────────
# 1. Hash do CPF
# ─────────────────────────────────────────────────────────────

class TestHashCPF:

    def test_hash_cpf_digitos_apenas(self, mapper):
        """CPF deve ter pontuação removida antes do hash."""
        hash1 = mapper._hash_cpf("123.456.789-00")
        hash2 = mapper._hash_cpf("12345678900")
        assert hash1 == hash2

    def test_hash_cpf_sha256_com_salt(self, mapper):
        """Hash deve ser SHA-256(cpf+salt) — ordem: CPF primeiro, salt depois.
        BUG-04 DOCUMENTADO: implementação usa '{cpf}{salt}', não '{salt}{cpf}'.
        Teste alinhado com a implementação (fonte de verdade para hashes já gerados).
        """
        cpf_digits = "12345678900"
        esperado = hashlib.sha256(f"{cpf_digits}{SALT}".encode()).hexdigest()
        assert mapper._hash_cpf("123.456.789-00") == esperado

    def test_hash_cpf_diferente_sem_salt(self, mapper):
        """Hash com salt diferente do SHA-256 simples."""
        cpf_digits = "12345678900"
        sem_salt = hashlib.sha256(cpf_digits.encode()).hexdigest()
        assert mapper._hash_cpf(cpf_digits) != sem_salt

    def test_hash_cpf_deterministico(self, mapper):
        """Mesmo CPF sempre gera o mesmo hash."""
        h1 = mapper._hash_cpf("12345678900")
        h2 = mapper._hash_cpf("12345678900")
        assert h1 == h2

    def test_hash_cpf_diferente_para_cpfs_distintos(self, mapper):
        """CPFs distintos geram hashes distintos."""
        h1 = mapper._hash_cpf("12345678900")
        h2 = mapper._hash_cpf("98765432100")
        assert h1 != h2


# ─────────────────────────────────────────────────────────────
# 2. Mapeamento Patient → PESSOA
# ─────────────────────────────────────────────────────────────

class TestMapPatient:

    def test_map_retorna_campos_obrigatorios(self, mapper, fhir_patient_completo):
        resultado = mapper.map(fhir_patient_completo)
        campos = ["rnds_id", "cpf_hash", "nome_social", "data_nascimento",
                  "sexo_biologico", "municipio", "uf", "ativo", "fonte_dados"]
        for campo in campos:
            assert campo in resultado, f"Campo ausente: {campo}"

    def test_map_fonte_dados_rnds(self, mapper, fhir_patient_completo):
        resultado = mapper.map(fhir_patient_completo)
        assert resultado["fonte_dados"] == "RNDS"

    def test_map_rnds_id_correto(self, mapper, fhir_patient_completo):
        resultado = mapper.map(fhir_patient_completo)
        assert resultado["rnds_id"] == "rnds-patient-001"

    def test_map_nome_usual_tem_prioridade(self, mapper, fhir_patient_completo):
        """Nome 'usual' deve ter prioridade sobre 'official' (nome social)."""
        resultado = mapper.map(fhir_patient_completo)
        assert resultado["nome_social"] == "Joãozinho Santos"

    def test_map_fallback_nome_official(self, mapper, fhir_patient_sem_cpf):
        """Se não há nome 'usual', usa 'official'."""
        resultado = mapper.map(fhir_patient_sem_cpf)
        assert resultado["nome_social"] == "Sem CPF Silva"

    def test_map_sexo_masculino(self, mapper, fhir_patient_completo):
        resultado = mapper.map(fhir_patient_completo)
        assert resultado["sexo_biologico"] == "M"

    def test_map_sexo_feminino(self, mapper, fhir_patient_obito):
        resultado = mapper.map(fhir_patient_obito)
        assert resultado["sexo_biologico"] == "F"

    def test_map_sexo_unknown_vira_none(self, mapper, fhir_patient_sem_cpf):
        resultado = mapper.map(fhir_patient_sem_cpf)
        assert resultado["sexo_biologico"] is None

    def test_map_data_nascimento(self, mapper, fhir_patient_completo):
        resultado = mapper.map(fhir_patient_completo)
        assert resultado["data_nascimento"] == "1985-03-20"

    def test_map_ativo_true_vivo(self, mapper, fhir_patient_completo):
        resultado = mapper.map(fhir_patient_completo)
        assert resultado["ativo"] is True

    def test_map_ativo_false_obito(self, mapper, fhir_patient_obito):
        resultado = mapper.map(fhir_patient_obito)
        assert resultado["ativo"] is False

    def test_map_trigger_ppr_obito(self, mapper, fhir_patient_obito):
        """Paciente falecido deve disparar _trigger_ppr = True."""
        resultado = mapper.map(fhir_patient_obito)
        assert resultado.get("_trigger_ppr") is True

    def test_map_sem_trigger_ppr_vivo(self, mapper, fhir_patient_completo):
        """Paciente vivo não deve disparar PPR."""
        resultado = mapper.map(fhir_patient_completo)
        assert not resultado.get("_trigger_ppr")

    def test_map_cpf_hash_presente(self, mapper, fhir_patient_completo):
        resultado = mapper.map(fhir_patient_completo)
        assert resultado["cpf_hash"] is not None
        assert len(resultado["cpf_hash"]) == 64  # SHA-256 hex

    def test_map_sem_cpf_hash_none(self, mapper, fhir_patient_sem_cpf):
        resultado = mapper.map(fhir_patient_sem_cpf)
        assert resultado["cpf_hash"] is None

    def test_map_municipio_ibge(self, mapper, fhir_patient_completo):
        resultado = mapper.map(fhir_patient_completo)
        assert resultado["municipio"] == "PE260790"

    def test_map_uf(self, mapper, fhir_patient_completo):
        resultado = mapper.map(fhir_patient_completo)
        assert resultado["uf"] == "PE"


# ─────────────────────────────────────────────────────────────
# 3. Salt de instância é isolado
# ─────────────────────────────────────────────────────────────

class TestIsolamentoSalt:

    def test_salt_diferente_hash_diferente(self):
        """Dois mappers com salts distintos geram hashes diferentes para o mesmo CPF."""
        m1 = FHIRPatientMapper(instance_salt="salt-um")
        m2 = FHIRPatientMapper(instance_salt="salt-dois")
        cpf = "12345678900"
        assert m1._hash_cpf(cpf) != m2._hash_cpf(cpf)
