from sentinelhub import SHConfig, SentinelHubRequest, DataCollection, MimeType, CRS, BBox

# Configure your credentials
config = SHConfig()
config.sh_client_id = 'your-client-id'  # Replace with your Sentinel Hub client ID
config.sh_client_secret = 'your-client-secret'  # Replace with your Sentinel Hub client secret

# Paris bounding box (approximate)
paris_bbox = BBox(bbox=[2.2522, 48.8166, 2.4222, 48.8766], crs=CRS.WGS84)

request = SentinelHubRequest(
    data_folder='paris_sat',
    evalscript="""
    //VERSION=3
    function setup() {
      return {
        input: ["B04", "B03", "B02"],
        output: { bands: 3 }
      };
    }
    function evaluatePixel(sample) {
      return [sample.B04, sample.B03, sample.B02];
    }
    """,
    input_data=[
        SentinelHubRequest.input_data(
            data_collection=DataCollection.SENTINEL2_L1C,
            time_interval=('2025-05-01', '2025-05-27'),
            mosaicking_order='mostRecent'
        )
    ],
    responses=[
        SentinelHubRequest.output_response('default', MimeType.PNG)
    ],
    bbox=paris_bbox,
    size=(512, 512),
    config=config
)

image = request.get_data(save_data=True)
print('Image downloaded to paris_sat/')
