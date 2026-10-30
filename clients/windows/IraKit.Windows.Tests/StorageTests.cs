using IraKit;

namespace IraKit.Windows.Tests;

public class StorageTests
{
    [Fact]
    public void The_device_key_round_trips_through_Credential_Manager_and_can_be_removed()
    {
        var store = new DeviceKeyStore($"Ira for Windows/tests/{Guid.NewGuid():N}");
        try
        {
            Assert.Null(store.Load());
            store.Save("irad_test-key");
            Assert.Equal("irad_test-key", store.Load());
            store.Save("irad_replaced");
            Assert.Equal("irad_replaced", store.Load());
        }
        finally
        {
            store.Delete();
        }
        Assert.Null(store.Load());
        store.Delete(); // removing what is not there is fine
    }

    [Fact]
    public void Settings_round_trip_and_a_damaged_file_means_not_paired()
    {
        var path = Path.Combine(Path.GetTempPath(), $"ira-settings-{Guid.NewGuid():N}.json");
        try
        {
            var settings = new DeviceSettings
            {
                Server = "https://ira.example.com",
                DeviceId = 7,
                Label = "Office PC",
                AllowedSkills = ["files", "screen"],
            };
            settings.Save(path);
            var loaded = DeviceSettings.Load(path);
            Assert.Equal(("https://ira.example.com", 7L, "Office PC"), (loaded!.Server, loaded.DeviceId, loaded.Label));
            Assert.Equal(["files", "screen"], loaded.AllowedSkills);
            Assert.Contains("\"allowed_skills\"", File.ReadAllText(path));

            File.WriteAllText(path, "{ not json");
            Assert.Null(DeviceSettings.Load(path));
        }
        finally
        {
            DeviceSettings.Delete(path);
        }
        Assert.Null(DeviceSettings.Load(path));
    }
}
