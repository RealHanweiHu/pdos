export type DevelopmentBomType = "cost" | "ebom" | "prototype";

export type ProductSpecification = {
  id: string;
  project_id: string;
  created_by_user_id: string;
  code: string;
  title: string;
  version: number;
  requirement_id: string | null;
  owner_user_id: string | null;
  verification_method: string | null;
  acceptance_criteria: string | null;
  criticality: "standard" | "key";
  content: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type BomItemCost = {
  currency: string;
  unit_cost: string;
  cost_category: string | null;
};

export type DevelopmentBomItem = {
  id: string;
  bom_id: string;
  parent_item_id: string | null;
  line_number: number;
  part_number: string;
  description: string;
  quantity: string;
  unit: string;
  material_reference: string | null;
  attributes: Record<string, unknown>;
  cost: BomItemCost | null;
  created_at: string;
  updated_at: string;
};

export type DevelopmentBom = {
  id: string;
  project_id: string;
  specification_id: string | null;
  created_by_user_id: string;
  bom_type: DevelopmentBomType;
  code: string;
  name: string;
  version: number;
  notes: string | null;
  items: DevelopmentBomItem[];
  created_at: string;
  updated_at: string;
};

export type ErpBomReference = {
  id: string;
  project_id: string;
  bom_id: string | null;
  reference_type: "mbom" | "production_version" | "routing";
  source_system: string;
  external_id: string;
  external_url: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type ProductEngineeringRegister = {
  specifications: ProductSpecification[];
  boms: DevelopmentBom[];
  erpReferences: ErpBomReference[];
};

export type SpecificationCreateInput = {
  code: string;
  title: string;
  version: number;
  content: Record<string, unknown>;
};

export type DevelopmentBomCreateInput = {
  specification_id: string | null;
  bom_type: DevelopmentBomType;
  code: string;
  name: string;
  version: number;
  notes: string | null;
};
