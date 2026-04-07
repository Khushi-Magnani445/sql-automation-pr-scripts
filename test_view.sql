CREATE VIEW test_view AS SELECT id, name FROM users;
CREATE VIEW test_view AS SELECT id, name, email FROM users;
CREATE VIEW test_view AS SELECT id, name, email, department, salary,address,phone,bonus FROM users;
CREATE OR REPLACE VIEW test_view_2 as select * from test_view;