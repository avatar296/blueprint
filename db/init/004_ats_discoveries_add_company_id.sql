-- Link ATS discoveries to sourced companies for filtered catalog scraping.

ALTER TABLE ats_discoveries ADD COLUMN company_id UUID REFERENCES companies(id);
CREATE INDEX idx_ats_disc_company_id ON ats_discoveries (company_id) WHERE company_id IS NOT NULL;
