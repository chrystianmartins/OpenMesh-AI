use assert_cmd::Command;

#[test]
fn prints_health_status() {
    let mut cmd = Command::cargo_bin("worker").expect("binary should compile");
    cmd.arg("health");
    cmd.assert().success();
}
