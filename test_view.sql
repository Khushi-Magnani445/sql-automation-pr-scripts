CREATE VIEW test_view AS SELECT id, name FROM users;
CREATE VIEW test_view AS SELECT id, name, email FROM users;
CREATE VIEW advanced_employee_view AS SELECT id AS employee_id, name AS full_name, department, location, manager_id FROM users;
