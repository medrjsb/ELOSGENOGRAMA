-- ============================================================
-- ELOS — RPCs de salvar/carregar genograma
--
-- O schema `elos` não é exposto pela API REST. O front acessa os dados só por
-- estas funções em `public`, que rodam como definer mas filtram tudo por
-- auth.uid(): cada clínico só enxerga e altera os próprios genogramas.
-- Reverter: DROP FUNCTION de cada função abaixo (nenhuma tabela é alterada).
-- ============================================================

-- Garante o registro do clínico ligado ao usuário autenticado e devolve o id.
CREATE OR REPLACE FUNCTION public.elos_current_clinician_id()
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_uid uuid := auth.uid();
  v_id  uuid;
BEGIN
  IF v_uid IS NULL THEN
    RAISE EXCEPTION 'Autenticação obrigatória' USING ERRCODE = '28000';
  END IF;

  SELECT c.id INTO v_id FROM elos.clinicians c WHERE c.auth_user_id = v_uid;
  IF v_id IS NOT NULL THEN
    RETURN v_id;
  END IF;

  INSERT INTO elos.clinicians (auth_user_id, full_name)
  SELECT v_uid, coalesce(nullif(u.raw_user_meta_data->>'full_name', ''), u.email, 'Clínico')
  FROM auth.users u WHERE u.id = v_uid
  ON CONFLICT (auth_user_id) DO NOTHING;

  SELECT c.id INTO v_id FROM elos.clinicians c WHERE c.auth_user_id = v_uid;
  RETURN v_id;
END;
$$;

-- Cria (p_id nulo) ou atualiza um genograma do clínico atual.
CREATE OR REPLACE FUNCTION public.elos_save_genogram(p_id uuid, p_title text, p_snapshot jsonb)
RETURNS TABLE (id uuid, title text, version integer, updated_at timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_clinician uuid := public.elos_current_clinician_id();
  v_title     text := left(coalesce(nullif(btrim(p_title), ''), 'Família sem título'), 200);
BEGIN
  IF p_snapshot IS NULL OR jsonb_typeof(p_snapshot) <> 'object' THEN
    RAISE EXCEPTION 'Snapshot inválido' USING ERRCODE = '22023';
  END IF;
  IF pg_column_size(p_snapshot) > 5 * 1024 * 1024 THEN
    RAISE EXCEPTION 'Genograma excede 5 MB' USING ERRCODE = '54000';
  END IF;

  IF p_id IS NULL THEN
    RETURN QUERY
      INSERT INTO elos.genograms AS g (clinician_id, title, snapshot)
      VALUES (v_clinician, v_title, p_snapshot)
      RETURNING g.id, g.title, g.version, g.updated_at;
    RETURN;
  END IF;

  RETURN QUERY
    UPDATE elos.genograms AS g
       SET title = v_title, snapshot = p_snapshot, version = g.version + 1
     WHERE g.id = p_id AND g.clinician_id = v_clinician AND g.is_active
    RETURNING g.id, g.title, g.version, g.updated_at;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Genograma não encontrado' USING ERRCODE = 'P0002';
  END IF;
END;
$$;

-- Lista os genogramas ativos do clínico atual (sem o snapshot).
CREATE OR REPLACE FUNCTION public.elos_list_genograms()
RETURNS TABLE (id uuid, title text, version integer, updated_at timestamptz, pessoas integer)
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT g.id, g.title, g.version, g.updated_at,
         coalesce(jsonb_array_length(g.snapshot->'people'), 0)
    FROM elos.genograms g
   WHERE g.clinician_id = public.elos_current_clinician_id() AND g.is_active
   ORDER BY g.updated_at DESC
   LIMIT 200;
$$;

-- Devolve um genograma do clínico atual.
CREATE OR REPLACE FUNCTION public.elos_get_genogram(p_id uuid)
RETURNS TABLE (id uuid, title text, version integer, updated_at timestamptz, snapshot jsonb)
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT g.id, g.title, g.version, g.updated_at, g.snapshot
    FROM elos.genograms g
   WHERE g.id = p_id AND g.clinician_id = public.elos_current_clinician_id() AND g.is_active;
$$;

-- Exclusão lógica: preserva o histórico clínico (prontuário é documento legal).
CREATE OR REPLACE FUNCTION public.elos_archive_genogram(p_id uuid)
RETURNS boolean
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
  UPDATE elos.genograms g SET is_active = false
   WHERE g.id = p_id AND g.clinician_id = public.elos_current_clinician_id() AND g.is_active
  RETURNING true;
$$;

REVOKE ALL ON FUNCTION public.elos_current_clinician_id()                FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.elos_save_genogram(uuid, text, jsonb)       FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.elos_list_genograms()                       FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.elos_get_genogram(uuid)                     FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.elos_archive_genogram(uuid)                 FROM PUBLIC, anon;

GRANT EXECUTE ON FUNCTION public.elos_current_clinician_id()             TO authenticated;
GRANT EXECUTE ON FUNCTION public.elos_save_genogram(uuid, text, jsonb)    TO authenticated;
GRANT EXECUTE ON FUNCTION public.elos_list_genograms()                    TO authenticated;
GRANT EXECUTE ON FUNCTION public.elos_get_genogram(uuid)                  TO authenticated;
GRANT EXECUTE ON FUNCTION public.elos_archive_genogram(uuid)              TO authenticated;
