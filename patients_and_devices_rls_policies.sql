-- 1) Enable RLS on patients
ALTER TABLE public.patients ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "doctor can select linked patients" ON public.patients;
CREATE POLICY "doctor can select linked patients"
ON public.patients
FOR SELECT
TO authenticated
USING (
  EXISTS (
    SELECT 1
    FROM public.doctor_patient dp
    WHERE dp.doctor_id = current_setting('app.current_user_id')::text
      AND dp.patient_id = public.patients.id
  )
);

-- 2) Enable RLS on devices
ALTER TABLE public.devices ENABLE ROW LEVEL SECURITY;


DROP POLICY IF EXISTS "doctor can select linked devices" ON public.devices;

CREATE POLICY "doctor can select linked devices"
ON public.devices
FOR SELECT
TO authenticated
USING (
  EXISTS (
    SELECT 1
    FROM public.doctor_patient dp
    WHERE dp.doctor_id = current_setting('app.current_user_id', true)::text
      AND dp.patient_id = public.devices.patient_id
  )
);