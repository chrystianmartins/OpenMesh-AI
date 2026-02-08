use assert_cmd::Command;

#[test]
fn shows_help() {
    let mut cmd = Command::cargo_bin("openmesh-worker").expect("binary should compile");
    cmd.arg("--help");
    cmd.assert().success();
}
